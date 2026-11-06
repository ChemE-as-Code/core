"""The process YAML loaded and checked: ids, units, bases, ports, links and balances.

Rules (``cheme.process-*``), each finding naming the file, line, rule and a hint:

- ``process-schema``: the file does not follow ``cheme/process/v1`` (versioned errors);
- ``process-id``, ``process-duplicate-id``: ids are stable identifiers, unique in the flowsheet;
- ``process-unit``, ``process-basis``, ``process-gauge-default``, ``process-normal-conditions``,
  ``process-enthalpy-reference``, ``process-pressure``: every quantity has a known unit and basis;
  gauge pressure only as an explicit unit; ``Nm3/h`` needs ``units.normal_conditions``;
- ``process-case``: state keyed by declared cases, one default;
- ``process-port``, ``process-port-reused``, ``process-delegation``, ``process-refine-pending``,
  ``process-port-open``: every stream runs between declared ports, a boundary stream at a step
  port delegates a block port, a port carries one stream;
- ``process-template``, ``process-component``, ``process-composition-sum``: materials;
- ``process-balance``, ``process-balance-not-evaluable``, ``process-balance-unsupported``:
  steady-state mass and component balances per block and per step; a reactive block or step
  (``reactions:``, or ``balance_scope: reactive``) balances mass and elements instead of
  components, and its component changes must be explained by extents of its reactions; a
  block or step with a ``crystallizer:`` balances mass and elements (a dissolved component
  becomes a solid one, :mod:`.solids`);
- ``process-crystallizer``, ``process-solid-separation``, ``process-solid``: a crystallizer or
  filter whose components, ports or solubility range do not fit, and solids in a stream said to
  be vapour (:func:`.crystallization.rules`); ``process-dryer``: a dryer whose volatiles, ports
  or energy port do not fit (:func:`.dryer.rules`);
- ``process-still``: a batch still whose ports, charge, feed or references do not fit, or
  whose volatile components lack the volatility data (vapour pressures, relative volatilities)
  or, for a boil-up in kW, heats of vaporization (info: no duty), and (warning) a
  heat_of_vaporization too small for kJ/kmol (one in kJ/mol) (:func:`.batch_still.rules`);
- ``process-energy-balance`` (warning), ``process-energy-balance-unsupported`` (info): the
  energy balance of a block or step whose streams carry enthalpies (:mod:`.energy`): enthalpy
  flows against the energy streams crossing it; a reacting node or an inconsistent enthalpy
  reference is reported as unsupported, never as a number;
- ``process-energy-port``: an ``energy_port`` that names no energy port of its block or step,
  or (warning) one on a node no model gives a duty (:func:`.duties.rules`, ADR 0059);
- ``process-terminal``: a terminal gives ``utility:`` without ``category: utility``;
- ``process-reactor``: a reactor model (``reactor:``) that cannot be solved as declared:
  conversion without a conversion per reaction, equilibrium without reactions, an irreversible
  reaction at equilibrium (warning), a Gibbs reactor naming reactions; a vented batch or
  semi-batch whose ``batch.vent`` stream is no outlet of it or its only one, whose vent
  components are not declared (or, warning, formed by none of its reactions), or a dose that
  passes gas through without a vent (ADR 0054);
- ``process-heat-of-reaction`` (warning): a given heat of reaction more than 2 % (and
  1000 kJ/kmol) from the one of the components' ideal-gas formation data;
- ``process-catalyst``: a reactor names a catalyst ``process/catalysts.yaml`` does not declare,
  or (warning) runs outside the catalyst's window (temperature or pressure of its streams), is
  fed one of its poisons, or holds another catalyst than its reactions' rates were measured on
  (the ``cheme.catalyst-*`` rules of that file: :mod:`chemeascode.domains.chemistry.catalysts`);
- ``process-reaction``: a block or step names a reaction ``process/reactions.yaml`` does not
  declare (the ``cheme.reaction-*`` rules of that file: :mod:`chemeascode.domains.chemistry.
  reactions`);
  ``process-component-balance-not-evaluable``: the mass balance closes, but the component
  balance lacks compositions;
- ``process-calculated-stale``: a calculated value's input fingerprint differs from its
  current inputs (see :mod:`.props`);
- ``process-link-unresolved``: info until a gate requires links (``kind: process-links``);
- ``process-aggregate``: a ``bfd.aggregate`` pair names a node that is not on the BFD;
- ``process-tear``: a tear stream (``tears:``, ADR 0060) propagate cannot iterate: an unknown
  or energy stream, one not between two steps, one named twice, a guess in undeclared
  components or flow units or whose fractions do not sum to 1 (errors), a stream whose flow
  and composition are both given or assumed (warning).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE, Catalysts
from chemeascode.domains.chemistry.catalysts import SCHEMA as CATALYSTS_SCHEMA
from chemeascode.domains.chemistry.catalysts import rules as catalyst_rules
from chemeascode.domains.chemistry.reactions import (
    ATOMIC_MASS,
    REACTIONS_FILE,
    Reaction,
    Reactions,
    element_flows,
    fit_extents,
    key_component,
)
from chemeascode.domains.chemistry.reactions import rules as reaction_rules
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.schema import (
    CALCULATED_UNITS,
    DUTY_UNITS,
    FLOW_UNITS,
    PRESSURE_UNITS,
    TEMPERATURE_UNITS,
    Block,
    Flowsheet,
    Materials,
    Node,
    Port,
    StreamDef,
    Tolerance,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.units import to_kpa_abs as to_kpa_abs  # kept importable here

#: kJ/(kmol K)
from chemeascode.foundation.yamlsource import _compose, _yaml_line, syntax_finding

GAS_CONSTANT = 8.314462618
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


@dataclass
class End:
    """One end of a stream: ``NODE.port`` resolved."""

    node: str
    port: str


@dataclass
class Process:
    """Both process files, parsed, with what the rules and the generator need."""

    root: Path
    materials: Materials | None
    flowsheet: Flowsheet
    flowsheet_doc: Any = None
    materials_doc: Any = None
    reactions: Reactions | None = None
    reactions_doc: Any = None
    catalysts: Catalysts | None = None
    catalysts_doc: Any = None
    #: The schema findings of process/catalysts.yaml (reported by :func:`rules`).
    catalysts_findings: list[Finding] = field(default_factory=list)
    #: kind of each node id: feed, product, block or step.
    kinds: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fs = self.flowsheet
        for kind, items in (
            ("feed", fs.feeds),
            ("product", fs.products),
            ("block", fs.blocks),
            ("step", fs.steps),
        ):
            for item in items:
                self.kinds.setdefault(item.id, kind)
                self.nodes.setdefault(item.id, item)

    # -- structure ------------------------------------------------------------------------------

    def end(self, text: str) -> End | None:
        node, dot, port = text.partition(".")
        return End(node.strip(), port.strip()) if dot and node and port else None

    def port(self, end: End) -> Port | None:
        node = self.nodes.get(end.node)
        return next((p for p in node.ports if p.id == end.port), None) if node else None

    def container(self, node_id: str) -> str:
        """The BFD node of *node_id*: a step's block, else the node itself."""
        if self.kinds.get(node_id) == "step":
            return self.nodes[node_id].block  # type: ignore[attr-defined]
        return node_id

    def home(self, node_id: str) -> str | None:
        """The block *node_id* is drawn in: a step's block, a nested block's parent; None for a
        top-level node (feed, product, block without parent)."""
        kind = self.kinds.get(node_id)
        if kind == "step":
            return self.nodes[node_id].block  # type: ignore[attr-defined]
        if kind == "block":
            parent = self.nodes[node_id].parent  # type: ignore[attr-defined]
            return parent if self.kinds.get(parent or "") == "block" else None
        return None

    def ancestors(self, node_id: str) -> list[str]:
        """The blocks around *node_id*, innermost first (a parent cycle stops at the repeat)."""
        found: list[str] = []
        at = self.home(node_id)
        while at is not None and at not in found and at != node_id:
            found.append(at)
            at = self.home(at)
        return found

    def top(self, node_id: str) -> str:
        """The BFD node of *node_id*: its outermost block, else the node itself."""
        around = self.ancestors(node_id)
        return around[-1] if around else node_id

    def within(self, node_id: str, block: str) -> bool:
        """Whether *node_id* is *block* or drawn inside it, at any depth."""
        return node_id == block or block in self.ancestors(node_id)

    def level(self, a: str, b: str) -> str | None:
        """The innermost block holding both nodes (None: the top level)."""
        around = self.ancestors(b)
        return next((x for x in self.ancestors(a) if x in around), None)

    def lift(self, end: End, level: str | None) -> End | None:
        """Where *end* is seen from inside *level* (None: the BFD): up through the port each
        port delegates until the node is drawn in *level*; None if a port on the way delegates
        nothing (or *level* is not around the node)."""
        seen = 0
        while self.home(end.node) != level:
            port = self.port(end)
            home = self.home(end.node)
            if port is None or not port.delegates or home is None or seen > len(self.kinds):
                return None
            end, seen = End(home, port.delegates), seen + 1
        return end

    def bfd_end(self, end: End) -> End | None:
        """Where *end* is on the BFD: a step port by the block port it delegates."""
        return self.lift(end, None)

    def ends(self, stream: StreamDef) -> tuple[End | None, End | None]:
        return self.end(stream.from_), self.end(stream.to)

    def crossing(self, stream: StreamDef) -> bool:
        """Whether *stream* crosses a BFD boundary (shown on the BFD)."""
        a, b = self.ends(stream)
        if a is None or b is None or a.node not in self.kinds or b.node not in self.kinds:
            return False
        return self.top(a.node) != self.top(b.node)

    def steps_of(self, block: str) -> list[Any]:
        return [s for s in self.flowsheet.steps if s.block == block]

    def children(self, block: str) -> list[Any]:
        """The blocks whose parent is *block*."""
        return [b for b in self.flowsheet.blocks if b.parent == block and b.id != block]

    def inside(self, block: str) -> list[Any]:
        """What the PFD draws inside *block*: its steps and nested blocks."""
        return [*self.steps_of(block), *self.children(block)]

    def components(self) -> dict[str, Any]:
        return {c.id: c for c in (self.materials.components if self.materials else [])}

    def templates(self) -> dict[str, Any]:
        return {t.id: t for t in (self.materials.templates if self.materials else [])}

    def ideal_gas(self) -> dict[str, Any]:
        """Component id -> its ideal-gas data (None when not given)."""
        return {c.id: c.ideal_gas for c in self.components().values()}

    def formulas(self) -> dict[str, str]:
        """Component id -> formula (empty when not given)."""
        return {c.id: c.formula for c in self.components().values()}

    def reactions_of(self, node_id: str) -> tuple[list[Reaction], list[str]]:
        """The reactions taking place in block or step *node_id* (a block's own and those of
        everything drawn inside it), and the ids among them that are not declared."""
        declared = self.reactions.by_id() if self.reactions else {}
        names: list[str] = []
        for other in self.nodes:
            if other == node_id or (
                self.kinds.get(other) in ("block", "step") and self.within(other, node_id)
            ):
                for name in getattr(self.nodes[other], "reactions", []) or []:
                    if name not in names:
                        names.append(name)
        return [declared[n] for n in names if n in declared], [
            n for n in names if n not in declared
        ]

    def reactive(self, node_id: str) -> bool:
        """Whether block or step *node_id* balances reactively: it, or something inside it,
        names reactions or has ``balance_scope: reactive``."""
        return any(
            bool(getattr(self.nodes[other], "reactions", None))
            or getattr(self.nodes[other], "balance_scope", None) == "reactive"
            or getattr(self.nodes[other], "reactor", None) == "gibbs"
            for other in self.nodes
            if other == node_id
            or (self.kinds.get(other) in ("block", "step") and self.within(other, node_id))
        )

    def phase_change(self, node_id: str) -> bool:
        """Whether block or step *node_id* holds a crystallizer (it, or something inside it):
        a dissolved component becomes a solid one, so it balances elements, not components
        (no reactions; it is no reactor)."""
        return any(
            getattr(self.nodes[other], "crystallizer", None) is not None
            for other in self.nodes
            if other == node_id
            or (self.kinds.get(other) in ("block", "step") and self.within(other, node_id))
        )


# -- loading ------------------------------------------------------------------------------------


def _schema_findings(name: str, kind: str, failure: ValidationError, doc: Any) -> list[Finding]:
    return [
        Finding(
            name,
            "error",
            "cheme.process-schema",
            f"cheme/process/v1 {kind}: {'.'.join(str(p) for p in e['loc']) or '(file)'}: "
            f"{e['msg']}",
            line=_yaml_line(doc, e["loc"]),
            hint=f"see `cheme schema process-{kind}`",
        )
        for e in failure.errors()
    ]


def _read(path: Path, name: str) -> tuple[Any, list[Finding]]:
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text) or {}, []
    except yaml.YAMLError as failure:
        return None, [syntax_finding(name, failure, text)]


def has_process(root: Path) -> bool:
    return (root / FLOWSHEET_FILE).is_file() or (root / MATERIALS_FILE).is_file()


def _load_optional(
    root: Path, name: str, model: Any, schema: str, rule: str, kind: str
) -> tuple[Any, Any, list[Finding]]:
    """An optional process file (reactions, catalysts): its model, its YAML nodes and its
    findings (None when the file is missing or does not follow its schema)."""
    path = root / name
    if not path.is_file():
        return None, None, []
    data, found = _read(path, name)
    doc = _compose(path)
    if data is None:
        return None, doc, found
    try:
        return model.model_validate(data), doc, found
    except ValidationError as failure:
        return (
            None,
            doc,
            found
            + [
                Finding(
                    name,
                    "error",
                    rule,
                    f"{schema}: {'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint=f"see `cheme schema process-{kind}`",
                )
                for e in failure.errors()
            ],
        )


def _load_reactions(root: Path) -> tuple[Reactions | None, Any, list[Finding]]:
    return _load_optional(
        root, REACTIONS_FILE, Reactions, "cheme/reactions/v1", "cheme.reaction-schema", "reactions"
    )


def load(root: Path) -> tuple[Process | None, list[Finding]]:
    """The process files of the repository at *root*, and their schema findings."""
    findings: list[Finding] = []
    materials = None
    materials_doc = None
    mpath = root / MATERIALS_FILE
    if mpath.is_file():
        data, found = _read(mpath, MATERIALS_FILE)
        findings += found
        materials_doc = _compose(mpath)
        if data is not None:
            try:
                materials = Materials.model_validate(data)
            except ValidationError as failure:
                findings += _schema_findings(MATERIALS_FILE, "materials", failure, materials_doc)
    fpath = root / FLOWSHEET_FILE
    if not fpath.is_file():
        return None, findings
    data, found = _read(fpath, FLOWSHEET_FILE)
    findings += found
    doc = _compose(fpath)
    if data is None:
        return None, findings
    try:
        flowsheet = Flowsheet.model_validate(data)
    except ValidationError as failure:
        return None, findings + _schema_findings(FLOWSHEET_FILE, "flowsheet", failure, doc)
    if not mpath.is_file():
        findings.append(
            Finding(
                FLOWSHEET_FILE,
                "warning",
                "cheme.process-template",
                f"{MATERIALS_FILE} does not exist: no component or template can be checked",
                hint=f"write {MATERIALS_FILE} (kind: materials)",
            )
        )
    reactions, reactions_doc, found = _load_reactions(root)
    findings += found
    # catalysts.yaml feeds only the catalyst rules: its schema findings go out with them, so
    # that a typo there does not stop the commands that never read it
    catalysts, catalysts_doc, found = _load_optional(
        root, CATALYSTS_FILE, Catalysts, CATALYSTS_SCHEMA, "cheme.catalyst-schema", "catalysts"
    )
    process = Process(root, materials, flowsheet, doc, materials_doc, reactions, reactions_doc)
    process.catalysts, process.catalysts_doc = catalysts, catalysts_doc
    process.catalysts_findings = found
    return process, findings


# -- quantities ---------------------------------------------------------------------------------


@dataclass
class Flows:
    """One stream's mass flow in kg/h, by component when the composition allows."""

    total: float | None
    components: dict[str, float] | None
    missing: list[str]


def stream_flows(process: Process, stream: StreamDef, case: str) -> Flows:
    """Mass flow (kg/h) of *stream* in *case*, total and per component, with what is missing."""
    fs = process.flowsheet
    state = stream.state.get(case)
    missing: list[str] = []
    if state is None or state.flow is None:
        return Flows(None, None, [f"{stream.id} flow"])
    unit = state.flow.unit or fs.units.flow
    basis, factor = FLOW_UNITS.get(unit, (None, 1.0))
    if basis is None:
        return Flows(None, None, [f"{stream.id} flow unit {unit!r}"])
    value = state.flow.value * factor
    comps = process.components()
    composition = state.composition
    template = process.templates().get(stream.template or "")
    names = list(template.components) if template else []
    if composition is not None:
        names += [n for n in composition.values if n not in names]
    fractions = {n: (composition.values.get(n, 0.0) if composition else 0.0) for n in names}
    mw = {n: getattr(comps.get(n), "molar_mass", None) for n in names}

    def need_mw() -> bool:
        lacking = [n for n in names if fractions[n] and not mw[n]]
        missing.extend(f"molar_mass of {n}" for n in lacking)
        return not lacking

    if basis == "normal_volume":
        nc = fs.units.normal_conditions
        if nc is None:
            return Flows(None, None, ["units.normal_conditions"])
        value = value * nc.pressure / (GAS_CONSTANT * nc.temperature)  # kmol/h
        basis = "mole"
    if basis == "mass":
        total = value
        if composition is None:
            return Flows(total, None, [f"{stream.id} composition"])
        if composition.basis == "mass_fraction":
            return Flows(total, {n: total * fractions[n] for n in names}, missing)
        if not need_mw():
            return Flows(total, None, missing)
        weights = {n: fractions[n] * (mw[n] or 0.0) for n in names}
        mix = sum(weights.values())
        if total == 0:
            # an empty stream (an empty first guess of a recycle, ADR 0060) carries no
            # component, whatever its fractions say: a reactor writes zero mole fractions
            return Flows(0.0, dict.fromkeys(names, 0.0), missing)
        if mix <= 0:
            return Flows(total, None, [f"{stream.id} composition"])
        return Flows(total, {n: total * w / mix for n, w in weights.items()}, missing)
    # mole basis: total kmol/h in value
    if composition is None:
        return Flows(None, None, [f"{stream.id} composition (to convert {unit} to kg/h)"])
    if not need_mw():
        return Flows(None, None, missing)
    if composition.basis == "mole_fraction":
        parts = {n: value * fractions[n] * (mw[n] or 0.0) for n in names}
        return Flows(sum(parts.values()), parts, missing)
    inverse = sum(fractions[n] / mw[n] for n in names if fractions[n] and mw[n])
    if value == 0:
        return Flows(0.0, dict.fromkeys(names, 0.0), missing)
    if inverse <= 0:
        return Flows(None, None, [f"{stream.id} composition"])
    total = value / inverse
    return Flows(total, {n: total * fractions[n] for n in names}, missing)


# -- balances -----------------------------------------------------------------------------------


@dataclass
class Balance:
    """The mass (and component) balance of one block or step in one case."""

    node: str
    kind: str  # block or step
    status: str  # ok, imbalance, not-evaluable, unsupported, no-streams
    inlet: float = 0.0
    outlet: float = 0.0
    missing: list[str] = field(default_factory=list)
    components: dict[str, tuple[float, float]] = field(default_factory=dict)
    failing: list[str] = field(default_factory=list)
    streams_in: list[str] = field(default_factory=list)
    streams_out: list[str] = field(default_factory=list)
    #: Reactive balances: kmol/h of extent by reaction id, fitted to the component changes.
    extents: dict[str, float] = field(default_factory=dict)

    def entry(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "kind": self.kind,
            "status": self.status,
            "in_kg_h": round(self.inlet, 6),
            "out_kg_h": round(self.outlet, 6),
            "missing": self.missing,
            "failing": self.failing,
            "streams_in": self.streams_in,
            "streams_out": self.streams_out,
            **(
                {"extents_kmol_h": {k: round(v, 6) for k, v in self.extents.items()}}
                if self.extents
                else {}
            ),
        }


def _within(a: float, b: float, tol: Tolerance) -> bool:
    return abs(a - b) <= tol.abs + tol.rel * max(abs(a), abs(b))


def balance_of(process: Process, node: str, case: str) -> Balance:
    """Steady-state balance of block or step *node*: the material streams crossing its boundary;
    streams with both ends inside cancel (they are not counted). Mass always balances; a
    reactive node balances elements instead of components (see :func:`_reactive_balance`)."""
    fs = process.flowsheet
    kind = process.kinds.get(node, "block")
    item = process.nodes.get(node)
    tol = (item.tolerance if isinstance(item, Block) else None) or fs.tolerance
    if isinstance(item, Block) and item.balance_scope == "dynamic":
        return Balance(node, kind, "unsupported", missing=[f"balance_scope {item.balance_scope}"])

    def inside(node_id: str) -> bool:
        return node_id == node if kind == "step" else process.within(node_id, node)

    result = Balance(node, kind, "ok")
    flows_in: list[Flows] = []
    flows_out: list[Flows] = []
    for stream in fs.streams:
        if stream.kind != "material":
            continue
        a, b = process.ends(stream)
        if a is None or b is None or a.node not in process.kinds or b.node not in process.kinds:
            continue
        if inside(a.node) == inside(b.node):
            continue
        flows = stream_flows(process, stream, case)
        if inside(b.node):
            result.streams_in.append(stream.id)
            flows_in.append(flows)
        else:
            result.streams_out.append(stream.id)
            flows_out.append(flows)
    if not result.streams_in and not result.streams_out:
        result.status = "no-streams"
        return result
    every = flows_in + flows_out
    if any(f.total is None for f in every):
        result.status = "not-evaluable"
        result.missing = [m for f in every if f.total is None for m in f.missing]
        return result
    result.inlet = sum(f.total or 0.0 for f in flows_in)
    result.outlet = sum(f.total or 0.0 for f in flows_out)
    if not _within(result.inlet, result.outlet, tol):
        result.failing.append(f"mass {result.inlet:.6g} kg/h in, {result.outlet:.6g} kg/h out")
    if process.reactive(node) or process.phase_change(node):
        _reactive_balance(process, node, flows_in, flows_out, tol, result)
    elif all(f.components is not None for f in every):
        names: list[str] = []
        for f in every:
            names += [n for n in f.components or {} if n not in names]
        for name in names:
            cin = sum((f.components or {}).get(name, 0.0) for f in flows_in)
            cout = sum((f.components or {}).get(name, 0.0) for f in flows_out)
            result.components[name] = (cin, cout)
            if not _within(cin, cout, tol):
                result.failing.append(f"{name} {cin:.6g} kg/h in, {cout:.6g} kg/h out")
    else:
        result.missing = sorted({m for f in every for m in f.missing})
    if result.failing:
        result.status = "imbalance"
    return result


def _reactive_balance(
    process: Process,
    node: str,
    flows_in: list[Flows],
    flows_out: list[Flows],
    tol: Tolerance,
    result: Balance,
) -> None:
    """Elements in and out (compared as kg/h of each element), then the component changes
    against the extents of the node's reactions: what the best extents leave unexplained, in
    kg/h, must be within the tolerance. What is missing goes to ``result.missing``."""
    every = flows_in + flows_out
    if any(f.components is None for f in every):
        result.missing = sorted({m for f in every for m in f.missing})
        return
    comps = process.components()
    mass_in: dict[str, float] = {}
    mass_out: dict[str, float] = {}
    for flows, into in ((flows_in, mass_in), (flows_out, mass_out)):
        for f in flows:
            for name, v in (f.components or {}).items():
                into[name] = into.get(name, 0.0) + v
    names = [*mass_in, *(n for n in mass_out if n not in mass_in)]
    for name in names:
        result.components[name] = (mass_in.get(name, 0.0), mass_out.get(name, 0.0))
    mw = {n: getattr(comps.get(n), "molar_mass", None) for n in names}
    lacking = [n for n in names if not mw[n] and (mass_in.get(n) or mass_out.get(n))]
    if lacking:
        result.missing = [f"molar_mass of {n}" for n in lacking]
        return
    moles_in = {n: v / (mw[n] or 1.0) for n, v in mass_in.items()}
    moles_out = {n: v / (mw[n] or 1.0) for n, v in mass_out.items()}
    formulas = process.formulas()
    elements_in = element_flows(moles_in, formulas)
    elements_out = element_flows(moles_out, formulas)
    if elements_in is None or elements_out is None:
        result.missing = [
            f"formula of {n}"
            for n in names
            if not formulas.get(n) and (mass_in.get(n) or mass_out.get(n))
        ] or ["a readable formula of every component"]
    else:
        for element in sorted({*elements_in, *elements_out}):
            a, b = elements_in.get(element, 0.0), elements_out.get(element, 0.0)
            if not _within(a * ATOMIC_MASS[element], b * ATOMIC_MASS[element], tol):
                result.failing.append(f"element {element} {a:.6g} kmol/h in, {b:.6g} kmol/h out")
    reactions, unknown = process.reactions_of(node)
    if unknown:
        result.missing += [f"reaction {r}" for r in unknown]
        return
    if not reactions:
        return
    declared = reactions
    reactions = [*reactions, *_crystallizations(process, node)]
    unnamed = sorted({n for r in reactions for n in r.stoichiometry if n not in comps})
    if unnamed:
        result.missing += [f"component {n}" for n in unnamed]
        return
    for name in (n for r in reactions for n in r.stoichiometry):
        mw.setdefault(name, getattr(comps.get(name), "molar_mass", None))
    lacking = sorted({n for r in reactions for n in r.stoichiometry if not mw[n]})
    if lacking:
        result.missing += [f"molar_mass of {n}" for n in lacking]
        return
    change = {n: moles_out.get(n, 0.0) - moles_in.get(n, 0.0) for n in names}
    extents, residual = fit_extents(reactions, change)
    # the crystallizers' phase changes explain solute becoming crystal; they are no reactions
    # (not reported as extents)
    result.extents = {r.id: extents[r.id] for r in declared}
    ids = ", ".join(r.id for r in reactions)
    for reaction in declared:
        xi = result.extents[reaction.id]
        turnover = -xi * sum(
            -v * (mw[n] or 0.0) for n, v in reaction.stoichiometry.items() if v < 0
        )
        if not reaction.reversible and turnover > tol.abs + tol.rel * max(
            result.inlet, result.outlet
        ):
            result.failing.append(
                f"reaction {reaction.id} runs backwards ({xi:.6g} kmol/h) but is not reversible"
            )
    for name, r in residual.items():
        cin, cout = result.components.get(name, (0.0, 0.0))
        if abs(r * (mw.get(name) or 0.0)) > tol.abs + tol.rel * max(abs(cin), abs(cout)):
            result.failing.append(
                f"{name} {cin:.6g} kg/h in, {cout:.6g} kg/h out: "
                f"{r * (mw.get(name) or 0.0):+.6g} kg/h not explained by reactions {ids}"
            )


def _crystallizations(process: Process, node: str) -> list[Reaction]:
    """One reversible phase change ``<step>:crystallization`` per crystallizer in *node* (the
    solute, and the hydrate's solvent, into the crystal), so that a reactive balance explains a
    crystallization, or the dissolution of a reslurry wash, next to the node's reactions. A
    crystallizer whose crystal form is not readable adds none (its own rules report it)."""
    from chemeascode.domains.process.crystallization import CrystallizationError, form_of

    found: list[Reaction] = []
    for other, item in process.nodes.items():
        spec = getattr(item, "crystallizer", None)
        if spec is None or not (
            other == node
            or (process.kinds.get(other) in ("block", "step") and process.within(other, node))
        ):
            continue
        try:
            form = form_of(process, spec)
        except (CrystallizationError, ValueError):
            continue
        stoichiometry = {spec.solute: -1.0, spec.crystal: 1.0}
        if form.hydrate:
            stoichiometry[spec.solvent] = -form.hydrate
        found.append(
            Reaction(
                id=f"{other}:crystallization",
                stoichiometry=stoichiometry,
                reversible=True,
                kind="phase-change",
            )
        )
    return found


def balances(process: Process, case: str | None = None) -> list[Balance]:
    case = case or process.flowsheet.default_case()
    found = [balance_of(process, b.id, case) for b in process.flowsheet.blocks]
    found += [balance_of(process, s.id, case) for s in process.flowsheet.steps]
    return found


# -- rules --------------------------------------------------------------------------------------


class _Out:
    def __init__(self, process: Process) -> None:
        self.process = process
        self.findings: list[Finding] = []

    def add(
        self,
        level: str,
        rule: str,
        message: str,
        loc: list[Any],
        ids: list[str] | None = None,
        hint: str = "",
        file: str = FLOWSHEET_FILE,
    ) -> None:
        doc = {
            FLOWSHEET_FILE: self.process.flowsheet_doc,
            MATERIALS_FILE: self.process.materials_doc,
            REACTIONS_FILE: self.process.reactions_doc,
            CATALYSTS_FILE: self.process.catalysts_doc,
        }.get(file)
        self.findings.append(
            Finding(
                file,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids or [],
                hint=hint,
            )
        )


def rules(process: Process, lists: dict[str, Any] | None = None, sheet_ids=()) -> list[Finding]:
    """Every ``cheme.process-*`` finding of the flowsheet and materials."""
    out = _Out(process)
    _materials_rules(out)
    _reaction_rules(out)
    _reactor_rules(out)
    _catalyst_rules(out)
    from chemeascode.domains.process.recipe import rules as recipe_rules

    out.findings += recipe_rules(process)
    _id_rules(out)
    _unit_rules(out)
    _port_rules(out)
    _state_rules(out)
    _balance_rules(out)
    _energy_rules(out)
    _terminal_rules(out)
    _calculated_rules(out)
    _tear_rules(out)
    _link_rules(out, lists or {}, set(sheet_ids))
    _bfd_rules(out)
    from chemeascode.domains.process.crystallization import rules as solid_rules

    out.findings += solid_rules(process)
    from chemeascode.domains.process.dryer import rules as dryer_rules

    out.findings += dryer_rules(process)
    from chemeascode.domains.process.batch_still import rules as still_rules

    out.findings += still_rules(process)
    from chemeascode.domains.process.duties import rules as duty_rules

    out.findings += duty_rules(process)
    return out.findings


def _bfd_rules(out: _Out) -> None:
    process = out.process
    options = process.flowsheet.bfd
    if options is None or isinstance(options.aggregate, bool):
        return
    for i, pair in enumerate(options.aggregate):
        for node_id in pair:
            if node_id not in process.kinds:
                problem = "is not a feed, product or block"
            elif process.kinds[node_id] == "step" or process.home(node_id) is not None:
                problem = "is not on the BFD (a step or nested block)"
            else:
                continue
            out.add(
                "error",
                "aggregate",
                f"bfd.aggregate pair {pair[0]}, {pair[1]}: {node_id} {problem}",
                ["bfd", "aggregate", i],
                [node_id],
                hint="name two top-level feeds, products or blocks, or use aggregate: true",
            )


def _materials_rules(out: _Out) -> None:
    process = out.process
    if process.materials is None:
        return
    seen: set[str] = set()
    for i, comp in enumerate(process.materials.components):
        if comp.id in seen:
            out.add(
                "error",
                "duplicate-id",
                f"component {comp.id} is declared twice",
                ["components", i],
                [comp.id],
                file=MATERIALS_FILE,
            )
        seen.add(comp.id)
    for i, template in enumerate(process.materials.templates):
        for name in template.components:
            if name not in seen:
                out.add(
                    "error",
                    "component",
                    f"template {template.id} names component {name}, which is not declared",
                    ["templates", i, "components"],
                    [template.id, name],
                    hint="add it to components:",
                    file=MATERIALS_FILE,
                )
    method = process.materials.property_method
    if method is not None and method.package is not None:
        from chemeascode.domains.process import property_packages

        if property_packages.get(method.package) is None:
            out.add(
                "error",
                "property-package",
                f"property_method.package {method.package!r} is not a known property package "
                f"({', '.join(p.id for p in property_packages.PACKAGES)})",
                ["property_method", "package"],
                hint="name a package cheme process props --coverage lists, or remove the line",
                file=MATERIALS_FILE,
            )


def _reaction_rules(out: _Out) -> None:
    process = out.process
    if process.reactions is not None:
        out.findings += reaction_rules(process.reactions, process.reactions_doc, process.formulas())
    fs = process.flowsheet
    declared = process.reactions.by_id() if process.reactions else {}
    for key, items in (("blocks", fs.blocks), ("steps", fs.steps)):
        for i, item in enumerate(items):
            unknown = [n for n in item.reactions if n not in declared]
            for name in unknown:
                where = (
                    f"{REACTIONS_FILE} does not declare it"
                    if process.reactions is not None
                    else f"{REACTIONS_FILE} does not exist"
                )
                out.add(
                    "error",
                    "reaction",
                    f"{key[:-1]} {item.id} names reaction {name}: {where}",
                    [key, i, "reactions"],
                    [item.id, name],
                    hint=f"declare it in {REACTIONS_FILE} (kind: reactions)",
                )
            names = set(item.reactions) - set(unknown)
            for name in item.conversion:
                if name in unknown:
                    continue
                if name not in names:
                    out.add(
                        "error",
                        "reaction",
                        f"{key[:-1]} {item.id}: conversion of {name}, which is not in its "
                        "reactions:",
                        [key, i, "conversion", name],
                        [item.id, name],
                        hint="add it to reactions: or remove the conversion",
                    )
                elif key_component(process.reactions.by_id()[name]) is None:  # type: ignore[union-attr]
                    out.add(
                        "error",
                        "reaction",
                        f"{key[:-1]} {item.id}: conversion of {name}, which has no key component",
                        [key, i, "conversion", name],
                        [item.id, name],
                        hint=f"give the reaction a conversion (key, value) in {REACTIONS_FILE}",
                    )
                elif not 0 < item.conversion[name] <= 1:
                    out.add(
                        "error",
                        "reaction",
                        f"{key[:-1]} {item.id}: conversion of {name} is "
                        f"{item.conversion[name]:g}, not in (0, 1]",
                        [key, i, "conversion", name],
                        [item.id, name],
                        hint="a fraction of the key component's inlet flow",
                    )


def _reactor_rules(out: _Out) -> None:
    from chemeascode.domains.chemistry.thermochemistry import (
        missing,
        outside,
        reaction_enthalpy,
    )

    process = out.process
    fs = process.flowsheet
    declared = process.reactions.by_id() if process.reactions else {}
    for key, items in (("blocks", fs.blocks), ("steps", fs.steps)):
        for i, item in enumerate(items):
            model = item.reactor
            loc = [key, i, "reactor"]
            what = f"{key[:-1]} {item.id}"
            reactions = [declared[n] for n in item.reactions if n in declared]
            if model == "gibbs" and item.reactions:
                out.add(
                    "error",
                    "reactor",
                    f"{what}: a Gibbs reactor takes every reaction among its components; it "
                    "names reactions",
                    loc,
                    [item.id],
                    hint="remove reactions: (or use reactor: equilibrium)",
                )
            elif (
                model in ("equilibrium", "conversion", "pfr", "cstr", "batch", "semibatch")
                and not item.reactions
            ):
                out.add(
                    "error",
                    "reactor",
                    f"{what}: reactor {model} names no reactions",
                    loc,
                    [item.id],
                    hint="add reactions: [ID, ...] from process/reactions.yaml",
                )
            elif model == "conversion":
                lacking = [
                    r.id for r in reactions if r.id not in item.conversion and r.conversion is None
                ]
                if lacking and getattr(item, "selectivity", None) is None:
                    out.add(
                        "error",
                        "reactor",
                        f"{what}: conversion reactor without a conversion of " + ", ".join(lacking),
                        loc,
                        [item.id, *lacking],
                        hint="give conversion: on the reaction or on the step",
                    )
            elif model == "equilibrium":
                phases = {r.phase == "liquid" for r in reactions if r.phase != "mixed"}
                for r in reactions:
                    given = r.equilibrium_constant
                    if r.phase == "mixed":
                        out.add(
                            "error",
                            "reactor",
                            f"{what}: no equilibrium of the mixed-phase reaction {r.id}",
                            loc,
                            [item.id, r.id],
                            hint="use a conversion reactor, or give the outlet as assumed",
                        )
                    elif r.phase == "liquid" and len(phases) > 1:
                        out.add(
                            "error",
                            "reactor",
                            f"{what}: equilibrium of gas-phase and liquid-phase reactions together "
                            f"({r.id} is liquid)",
                            loc,
                            [item.id, r.id],
                            hint="split them into two reactor steps",
                        )
                    if r.phase == "liquid" and getattr(item, "fugacity", "ideal") != "ideal":
                        out.add(
                            "warning",
                            "reactor",
                            f"{what}: fugacity {item.fugacity} is a gas's; the liquid-phase "
                            f"reaction {r.id} is solved on its own basis",
                            loc,
                            [item.id, r.id],
                            hint="remove fugacity:, or use the activity basis for a non-ideal "
                            "liquid",
                        )
                    if r.phase == "liquid" and (given is None or given.basis == "partial_pressure"):
                        out.add(
                            "error",
                            "reactor",
                            f"{what}: the liquid-phase reaction {r.id} has no equilibrium_constant "
                            "on mole_fraction, activity or concentration",
                            loc,
                            [item.id, r.id],
                            hint="give its equilibrium_constant with basis: (ideal-gas data give "
                            "the K of the gas)",
                        )
                    if not r.reversible:
                        out.add(
                            "warning",
                            "reactor",
                            f"{what}: equilibrium reactor with the irreversible reaction {r.id}",
                            loc,
                            [item.id, r.id],
                            hint="set reversible: true, or use a conversion reactor",
                        )
            if model == "pfr":
                lacking = [r.id for r in reactions if r.rate is None]
                for problem, missing_now in (
                    ("no bed:", item.bed is None),
                    ("no catalyst:", item.catalyst is None),
                    ("no rate law for " + ", ".join(lacking), bool(lacking)),
                ):
                    if missing_now:
                        out.add(
                            "error",
                            "reactor",
                            f"{what}: reactor pfr with {problem.rstrip(':')}",
                            loc,
                            [item.id],
                            hint="a fixed bed needs bed:, catalyst: and a rate: on each reaction",
                        )
            elif item.bed is not None:
                out.add(
                    "warning",
                    "reactor",
                    f"{what}: a bed is used by reactor: pfr only",
                    [key, i, "bed"],
                    [item.id],
                    hint="set reactor: pfr, or remove bed",
                )
            spec = getattr(item, "selectivity", None)
            if spec is not None:
                problems = []
                if model not in (None, "conversion"):
                    problems.append(f"selectivity is for a conversion reactor, not {model}")
                declared = [r.id for r in reactions if r.conversion is not None]
                if item.conversion or declared:
                    problems.append(
                        "give conversion per reaction or selectivity, not both"
                        + (
                            f" (reactions.yaml gives one for {', '.join(declared)})"
                            if declared
                            else ""
                        )
                    )
                if not any(r.stoichiometry.get(spec.key, 0) < 0 for r in reactions):
                    problems.append(f"the key {spec.key} is a reactant of none of its reactions")
                for product in spec.products:
                    if not any(r.stoichiometry.get(product, 0) > 0 for r in reactions):
                        problems.append(f"{product} is formed by none of its reactions")
                if not problems:  # the stoichiometry alone decides: a unit feed of the key
                    from chemeascode.domains.chemistry.reactions import selectivity_extents

                    try:
                        selectivity_extents(
                            reactions, spec.key, spec.conversion, spec.products, {spec.key: 1.0}
                        )
                    except ValueError as failure:
                        problems.append(str(failure))
                for problem in problems:
                    out.add(
                        "error",
                        "reactor",
                        f"{what}: {problem}",
                        [key, i, "selectivity"],
                        [item.id],
                        hint="selectivity: {key, conversion, products: {id: kmol formed per kmol "
                        "of the key converted}} on a conversion reactor",
                    )
            if model in ("batch", "semibatch"):
                _dosing_rules(out, item, [key, i], model, reactions)
                _vent_rules(out, item, [key, i], reactions)
            for kind, field_name in (("cstr", "tank"), ("batch", "batch")):
                spec = getattr(item, field_name, None)
                if model == kind or (kind == "batch" and model == "semibatch"):
                    kind = model
                    lacking = [r.id for r in reactions if r.rate is None]
                    phases = {r.phase == "liquid" for r in reactions if r.phase != "mixed"}
                    mixed = [r.id for r in reactions if r.phase == "mixed"]
                    per_kg = [r.id for r in reactions if r.rate and r.rate.basis == "catalyst_mass"]
                    no_loading = spec is not None and per_kg and spec.catalyst_loading is None
                    adiabatic_liquid = (
                        spec is not None and spec.heat == "adiabatic" and phases == {True}
                    )
                    no_heat = [r.id for r in reactions if r.heat_of_reaction is None]
                    comps = process.components()
                    no_cp = sorted(
                        {
                            n
                            for r in reactions
                            for n in r.stoichiometry
                            if not getattr(comps.get(n), "liquid_heat_capacity", None)
                        }
                    )
                    for problem, missing_now in (
                        (f"no {field_name}", spec is None),
                        ("no rate law for " + ", ".join(lacking), bool(lacking)),
                        ("gas-phase and liquid-phase reactions together", len(phases) > 1),
                        ("the mixed-phase reaction(s) " + ", ".join(mixed), bool(mixed)),
                        ("rates per kg of catalyst but no catalyst_loading", bool(no_loading)),
                        (
                            "an adiabatic liquid without heat_of_reaction of " + ", ".join(no_heat),
                            adiabatic_liquid and bool(no_heat),
                        ),
                        (
                            "an adiabatic liquid without liquid_heat_capacity of "
                            + ", ".join(no_cp),
                            adiabatic_liquid and bool(no_cp),
                        ),
                    ):
                        if missing_now:
                            out.add(
                                "error",
                                "reactor",
                                f"{what}: reactor {kind} with {problem}",
                                loc,
                                [item.id],
                                hint=f"a {kind} needs {field_name}: and a rate: on each "
                                "reaction, all of one phase",
                            )
                elif spec is not None:
                    out.add(
                        "warning",
                        "reactor",
                        f"{what}: {field_name} is used by reactor: "
                        f"{'batch or semibatch' if kind == 'batch' else kind} only",
                        [key, i, field_name],
                        [item.id],
                        hint=f"set reactor: {kind}, or remove {field_name}",
                    )
            if item.fugacity != "ideal" and model not in ("equilibrium", "gibbs"):
                out.add(
                    "warning",
                    "reactor",
                    f"{what}: fugacity {item.fugacity} is used by equilibrium and Gibbs "
                    "reactors only",
                    [key, i, "fugacity"],
                    [item.id],
                    hint="set reactor: equilibrium or gibbs, or remove fugacity",
                )
            elif item.fugacity == "peng_robinson":
                # what it carries in any case, forms by its reactions, or (Gibbs) may form
                carried: set[str] = {n for r in reactions for n in r.stoichiometry}
                for stream in fs.streams:
                    if not any(e is not None and e.node == item.id for e in process.ends(stream)):
                        continue
                    if model == "gibbs":
                        template = process.templates().get(stream.template or "")
                        carried |= set(template.components if template else [])
                    for state in stream.state.values():
                        comp = state.composition
                        carried |= {n for n, y in (comp.values.items() if comp else ()) if y > 0}
                comps = process.components()
                lacking = sorted(
                    n for n in carried if getattr(comps.get(n), "critical", None) is None
                )
                if lacking:
                    out.add(
                        "error",
                        "reactor",
                        f"{what}: fugacity peng_robinson without the critical constants of "
                        + ", ".join(lacking),
                        [key, i, "fugacity"],
                        [item.id, *lacking],
                        hint="give critical: {Tc, Pc, omega} in process/materials.yaml "
                        "(cheme chemistry thermo NAME prints them)",
                    )
            if item.approach and model not in ("equilibrium", "gibbs"):
                out.add(
                    "warning",
                    "reactor",
                    f"{what}: approach is used by equilibrium and Gibbs reactors only",
                    [key, i, "approach"],
                    [item.id],
                    hint="set reactor: equilibrium or gibbs, or remove approach",
                )
    if process.reactions is None:
        return
    data = process.ideal_gas()
    for i, reaction in enumerate(process.reactions.reactions):
        given = reaction.heat_of_reaction
        names = list(reaction.stoichiometry)
        if (
            given is None
            or reaction.phase in ("liquid", "mixed")  # ideal-gas data say nothing about these
            or missing(names, data)
            or outside(names, data, given.temperature)
        ):
            continue
        calculated = reaction_enthalpy(reaction.stoichiometry, data, given.temperature)
        if abs(given.value - calculated) > max(1000.0, 0.02 * abs(calculated)):
            out.add(
                "warning",
                "heat-of-reaction",
                f"reaction {reaction.id}: heat_of_reaction {given.value:.6g} kJ/kmol, the "
                f"components' ideal_gas data give {calculated:.6g} kJ/kmol at "
                f"{given.temperature:g} K",
                ["reactions", i, "heat_of_reaction"],
                [reaction.id],
                hint="check the coefficients (per kmol of extent as written), the value or the "
                "formation data",
                file=REACTIONS_FILE,
            )


def _dosing_rules(out: _Out, item: Any, at: list[Any], model: str, reactions: list[Any]) -> None:
    """A semi-batch's doses: on ``reactor: semibatch`` only, each an inlet stream of the step,
    one charge stream besides them, liquid-phase reactions."""
    process = out.process
    what = f"{at[0][:-1]} {item.id}"
    dosing = item.batch.dosing if item.batch is not None else []
    if model == "batch":
        if dosing:
            out.add(
                "error",
                "reactor",
                f"{what}: a batch with dosing",
                [*at, "batch", "dosing"],
                [item.id],
                hint="set reactor: semibatch, or remove batch.dosing",
            )
        return
    if item.batch is None:
        return  # said by the batch's rules
    problems = []
    if not dosing:
        problems.append("no dosing")
    inlets = [
        s.id
        for s in process.flowsheet.streams
        if (end := process.ends(s)[1]) is not None and end.node == item.id and s.kind == "material"
    ]
    if stray := [d.stream for d in dosing if d.stream not in inlets]:
        problems.append("the dosed stream(s) " + ", ".join(stray) + " are no inlet of it")
    charges = [s for s in inlets if s not in {d.stream for d in dosing}]
    if dosing and len(charges) != 1:
        problems.append(f"{len(charges)} charge streams (one inlet besides the doses)")
    if gas := [r.id for r in reactions if r.phase != "liquid"]:
        problems.append("the reaction(s) " + ", ".join(gas) + " not liquid-phase")
    for problem in problems:
        out.add(
            "error",
            "reactor",
            f"{what}: reactor semibatch with {problem}",
            [*at, "batch", "dosing"] if dosing else [*at, "reactor"],
            [item.id],
            hint="a semibatch: batch.dosing [{stream, time or profile}] naming its dosed inlet "
            "streams; its other inlet is the charge; liquid-phase reactions",
        )


def _vent_rules(out: _Out, item: Any, at: list[Any], reactions: list[Any]) -> None:
    """A vented batch or semi-batch (ADR 0054): the vent an outlet of the step besides the
    liquid's, its components declared and formed, liquid-phase reactions; a dose that passes
    gas through (``absorbed`` below 1) needs the vent."""
    process = out.process
    what = f"{at[0][:-1]} {item.id}"
    batch = item.batch
    if batch is None:
        return
    vent = batch.vent
    hint = (
        "batch.vent: {stream: the step's gas outlet, components: [ids formed], fraction: "
        "{id: share}}; the step's other outlet is the liquid"
    )
    if vent is None:
        if passing := [d.stream for d in batch.dosing if d.absorbed is not None and d.absorbed < 1]:
            out.add(
                "error",
                "reactor",
                f"{what}: the dose(s) {', '.join(passing)} pass gas through (absorbed below 1) "
                "but there is no batch.vent",
                [*at, "batch", "dosing"],
                [item.id],
                hint=hint,
            )
        return
    outlets = [
        s.id
        for s in process.flowsheet.streams
        if (end := process.ends(s)[0]) is not None and end.node == item.id and s.kind == "material"
    ]
    problems = []
    condenser = vent.condenser
    condensate = (
        condenser.returns if condenser is not None and condenser.returns != "vessel" else None
    )
    allowed = 3 if condensate is not None else 2
    if vent.stream not in outlets:
        problems.append(f"the vent stream {vent.stream} is no outlet of it")
    elif len(outlets) == 1:
        problems.append(
            f"the vent stream {vent.stream} is its only outlet: the liquid needs its own"
        )
    elif len(outlets) > allowed:
        problems.append(
            f"{len(outlets)} outlets (a vented batch has the liquid's and the vent"
            + (", and its condenser's condensate)" if condensate else ")")
        )
    if condensate is not None and condensate not in outlets:
        problems.append(f"the condenser's condensate stream {condensate} is no outlet of it")
    elif condensate is not None and len(outlets) < 3:
        problems.append("no outlet for the liquid besides the vent and the condensate")
    declared = process.components()
    if unknown := [n for n in vent.components if n not in declared]:
        problems.append("the vent component(s) " + ", ".join(unknown) + " not declared")
    for problem in problems:
        out.add(
            "error",
            "reactor",
            f"{what}: vent with {problem}",
            [*at, "batch", "vent"],
            [item.id],
            hint=hint,
        )
    # a semibatch's own rules already say its reactions are not liquid-phase
    if item.reactor == "batch" and (gas := [r.id for r in reactions if r.phase != "liquid"]):
        out.add(
            "error",
            "reactor",
            f"{what}: a vent takes liquid-phase reactions only: {', '.join(gas)} "
            + ("is" if len(gas) == 1 else "are")
            + " not",
            [*at, "batch", "vent"],
            [item.id],
            hint=hint,
        )
    _vent_template_rule(out, item, at, vent, declared)
    _vent_vapour_rules(out, item, at, vent, declared, reactions, outlets)
    unformed = [
        n
        for n in vent.components
        if n in declared and not any(r.stoichiometry.get(n, 0) > 0 for r in reactions)
    ]
    if unformed:
        out.add(
            "warning",
            "reactor",
            f"{what}: vent component(s) {', '.join(unformed)} formed by none of its reactions "
            "(nothing of it vents)",
            [*at, "batch", "vent", "components"],
            [item.id, *unformed],
            hint="list the gases the reactions form; a dosed gas passes through by dosing.absorbed",
        )


def _vent_condenser_temperature(
    out: _Out, item: Any, what: str, where: list[Any], condenser: Any
) -> None:
    """ADR 0062: a vent condenser below the vessel's temperature, the charge's in each case
    (an isothermal batch holds it; an adiabatic one starts at it). At or above it the condenser
    condenses nothing and heats the gas: its duty turns negative and the vent leaves hotter
    than the vessel. An error for an isothermal batch, a warning for an adiabatic one (its
    content may heat past the condenser)."""
    process = out.process
    fs = process.flowsheet
    dosed = {d.stream for d in item.batch.dosing}
    charges = [
        s
        for s in fs.streams
        if (end := process.ends(s)[1]) is not None
        and end.node == item.id
        and s.kind == "material"
        and s.id not in dosed
    ]
    if len(charges) != 1:
        return  # the batch's own rules say what its inlets lack
    charge = charges[0]
    isothermal = item.batch.heat == "isothermal"
    for case, state in charge.state.items():
        q = getattr(state, "temperature", None)
        if q is None:
            continue
        held = to_kelvin(q.value, q.unit or fs.units.temperature)
        if condenser.temperature < held:
            continue
        out.add(
            "error" if isothermal else "warning",
            "reactor",
            f"{what}: vent condenser at {condenser.temperature:g} K is not below the "
            f"vessel's {held:g} K (the charge {charge.id}, case {case}"
            + ("" if isothermal else ", where the adiabatic batch starts")
            + "): a vent condenser above the vessel's temperature condenses nothing and heats "
            "the gas",
            [*where, "condenser", "temperature"],
            [item.id, charge.id],
            hint="give vent.condenser.temperature below the batch's temperature (the coolant's "
            "outlet plus its approach), or drop the condenser",
        )
        return


def vent_volatile(process: Any, item: Any, reactions: list[Any]) -> list[str]:
    """The volatile components a vented batch's gas carries (ADR 0062): ``vent.vapour``'s list,
    else every component of its inlets' templates and its reactions with a vapour_pressure (a
    vent component is a gas, never one of them)."""
    vent = item.batch.vent
    if vent.vapour.components:
        return list(vent.vapour.components)
    declared = process.components()
    templates = process.templates()
    names: list[str] = []
    for s in process.flowsheet.streams:
        end = process.ends(s)[1]
        if end is None or end.node != item.id or s.kind != "material":
            continue
        if (t := templates.get(s.template or "")) is not None:
            names += t.components
    names += [n for r in reactions for n in r.stoichiometry]
    return [
        n
        for n in dict.fromkeys(names)
        if n not in vent.components and getattr(declared.get(n), "vapour_pressure", None)
    ]


def _vent_vapour_rules(
    out: _Out,
    item: Any,
    at: list[Any],
    vent: Any,
    declared: Any,
    reactions: list[Any],
    outlets: list[str],
) -> None:
    """ADR 0062: the vapour's components declared with a vapour_pressure, in the vent's (and a
    condensate stream's) template; a Henry component in the liquid's template; the condenser's
    energy_port an energy port of the step."""
    process = out.process
    what = f"{at[0][:-1]} {item.id}"
    where = [*at, "batch", "vent"]
    hint = (
        "vent.vapour: {components: [volatile ids with vapour_pressure]}; vent.condenser: "
        "{temperature: K, returns: vessel or a stream, energy_port: port}; vent.henry: "
        "{gas: {points: [[K, kPa]]}}"
    )
    errors: list[str] = []
    streams = {s.id: s for s in process.flowsheet.streams}
    templates = process.templates()

    def template_of(stream_id: str | None) -> Any:
        stream = streams.get(stream_id or "")
        return templates.get(stream.template or "") if stream is not None else None

    if vent.vapour is not None:
        volatile = vent_volatile(process, item, reactions)
        if unknown := [n for n in vent.vapour.components if n not in declared]:
            errors.append("vapour component(s) " + ", ".join(unknown) + " not declared")
        if lack := [
            n
            for n in vent.vapour.components
            if n in declared and getattr(declared[n], "vapour_pressure", None) is None
        ]:
            errors.append(
                "vapour component(s) " + ", ".join(lack) + " without a vapour_pressure (Antoine)"
            )
        if not volatile:
            out.add(
                "warning",
                "reactor",
                f"{what}: vent.vapour, but no component of it has a vapour_pressure: the gas "
                "carries no vapour",
                [*where, "vapour"],
                [item.id],
                hint="give the solvent's Antoine vapour_pressure in materials.yaml, or name the "
                "volatile components in vent.vapour.components",
            )
        known = [n for n in volatile if n in declared]
        condenser = vent.condenser
        condensate = (
            condenser.returns if condenser is not None and condenser.returns != "vessel" else None
        )
        for stream_id, role in ((vent.stream, "vent"), (condensate, "condensate")):
            template = template_of(stream_id)
            if template is None:
                continue
            if lacking := [n for n in known if n not in template.components]:
                errors.append(
                    f"the {role} stream {stream_id}'s template {template.id} lacks the vapour's "
                    + ", ".join(lacking)
                )
        if condenser is not None and condenser.energy_port is not None:
            port = next((q for q in item.ports if q.id == condenser.energy_port), None)
            if port is None or port.kind != "energy":
                errors.append(
                    f"the condenser's energy_port {condenser.energy_port} is no energy port of it"
                )
            elif condenser.energy_port == getattr(item, "energy_port", None):
                errors.append(
                    f"the condenser's energy_port {condenser.energy_port} is the step's own "
                    "energy_port (the jacket's): give the condenser its own energy stream"
                )
        if condenser is not None:
            _vent_condenser_temperature(out, item, what, where, condenser)
    if vent.henry:
        liquid = [
            s for s in outlets if s != vent.stream and s != getattr(vent.condenser, "returns", None)
        ]
        template = template_of(liquid[0]) if len(liquid) == 1 else None
        if template is not None and (
            lacking := [n for n in vent.henry if n in declared and n not in template.components]
        ):
            errors.append(
                f"the liquid stream {liquid[0]}'s template {template.id} lacks "
                + ", ".join(lacking)
                + " (vent.henry keeps it dissolved)"
            )
    for problem in errors:
        out.add("error", "reactor", f"{what}: vent with {problem}", where, [item.id], hint=hint)


def _vent_template_rule(out: _Out, item: Any, at: list[Any], vent: Any, declared: Any) -> None:
    """The vent stream's template holds what propagate writes into it: the vent's components
    and what a dose passing gas through (``absorbed`` below 1) carries (its stream's
    composition where stated, else its template's components)."""
    process = out.process
    streams = {s.id: s for s in process.flowsheet.streams}
    stream = streams.get(vent.stream)
    templates = process.templates()
    template = templates.get(stream.template or "") if stream is not None else None
    if template is None:
        return  # no such outlet, or no template: said by the stream rules
    needed: dict[str, str] = {n: "a vent component" for n in vent.components if n in declared}
    for dose in item.batch.dosing:
        if dose.absorbed is None or dose.absorbed >= 1 or dose.stream not in streams:
            continue
        dosed = streams[dose.stream]
        carried = {
            n
            for state in dosed.state.values()
            if state.composition is not None
            for n, y in state.composition.values.items()
            if y > 0
        }
        if not carried and (t := templates.get(dosed.template or "")) is not None:
            carried = set(t.components)
        for n in sorted(carried):
            needed.setdefault(n, f"the dose {dose.stream} passes it through")
    lacking = [n for n in needed if n not in template.components]
    if lacking:
        why = "; ".join(f"{n}: {needed[n]}" for n in lacking)
        out.add(
            "error",
            "reactor",
            f"{at[0][:-1]} {item.id}: vent stream {vent.stream}'s template {template.id} lacks "
            f"{', '.join(lacking)} ({why})",
            [*at, "batch", "vent", "stream"],
            [item.id, vent.stream],
            hint="add them to the vent stream's template",
        )


def _catalyst_rules(out: _Out) -> None:
    process = out.process
    out.findings += process.catalysts_findings
    if process.catalysts is not None:
        out.findings += catalyst_rules(
            process.catalysts, process.catalysts_doc, process.components()
        )
    declared = process.catalysts.by_id() if process.catalysts else {}
    fs = process.flowsheet
    for key, items in (("blocks", fs.blocks), ("steps", fs.steps)):
        for i, item in enumerate(items):
            name = item.catalyst
            if name is None:
                continue
            loc = [key, i, "catalyst"]
            what = f"{key[:-1]} {item.id}"
            cat = declared.get(name)
            if cat is None:
                where = (
                    f"{CATALYSTS_FILE} does not declare it"
                    if process.catalysts is not None
                    else f"{CATALYSTS_FILE} does not exist"
                )
                out.add(
                    "error",
                    "catalyst",
                    f"{what} names catalyst {name}: {where}",
                    loc,
                    [item.id, name],
                    hint=f"declare it in {CATALYSTS_FILE} (kind: catalysts)",
                )
                continue
            reactions, _ = process.reactions_of(item.id)
            for r in reactions:
                if r.rate is not None and r.rate.catalyst and r.rate.catalyst != name:
                    out.add(
                        "warning",
                        "catalyst",
                        f"{what} holds catalyst {name}, but the rate of {r.id} was measured on "
                        f"{r.rate.catalyst}",
                        loc,
                        [item.id, r.id],
                        hint="use kinetics of this catalyst, or say why they apply",
                    )
            for case in (c.id for c in fs.cases):
                _catalyst_window(out, item, name, cat, case, loc, what)


def _catalyst_window(out: _Out, item: Any, name: str, cat: Any, case: str, loc, what) -> None:
    """The streams across the boundary of reactor *item* (a step's, or a block's with
    everything inside it) against catalyst *cat*'s window, and its feeds against its
    poisons, in *case*."""
    process = out.process
    fs = process.flowsheet
    balance = balance_of(process, item.id, case)
    streams = {s.id: s for s in fs.streams}
    window = cat.window
    for sid in balance.streams_in + balance.streams_out if window is not None else []:
        state = streams[sid].state.get(case)
        if state is None:
            continue
        checks = (
            ("temperature", window.temperature, "K"),  # type: ignore[union-attr]
            ("pressure", window.pressure, "kPa(a)"),  # type: ignore[union-attr]
        )
        for field_name, bounds, unit in checks:
            q = getattr(state, field_name)
            if bounds is None or q is None:
                continue
            value = (
                to_kelvin(q.value, q.unit or fs.units.temperature)
                if field_name == "temperature"
                else to_kpa_abs(q.value, q.unit or fs.units.pressure)
            )
            if value is None:
                out.add(
                    "info",
                    "catalyst",
                    f"{what} ({case}): the {field_name} of stream {sid} is not checked against "
                    f"catalyst {name}'s window (unit {q.unit or 'default'}: not absolute or not "
                    "known)",
                    loc,
                    [item.id, sid, name],
                    hint="give it in K or °C, or as an absolute pressure",
                )
            elif not bounds[0] <= value <= bounds[1]:
                out.add(
                    "warning",
                    "catalyst",
                    f"{what} ({case}): stream {sid} at {value:.6g} {unit}, outside catalyst "
                    f"{name}'s {field_name} window {bounds[0]:g} to {bounds[1]:g} {unit}",
                    loc,
                    [item.id, sid, name],
                    hint="change the conditions, or the catalyst",
                )
    for poison in cat.poisons:
        for sid in balance.streams_in:
            state = streams[sid].state.get(case)
            comp = state.composition if state is not None else None
            if comp is not None and comp.values.get(poison, 0.0) > 0:
                out.add(
                    "warning",
                    "catalyst",
                    f"{what} ({case}): stream {sid} carries {poison}, a poison of catalyst {name}",
                    loc,
                    [item.id, sid, poison],
                    hint="remove it upstream (a guard bed), or say why it is harmless",
                )


def _id_rules(out: _Out) -> None:
    fs = out.process.flowsheet
    seen: dict[str, str] = {}
    for key in ("feeds", "products", "blocks", "steps", "streams"):
        for i, item in enumerate(getattr(fs, key)):
            if not _ID.match(item.id):
                out.add(
                    "error",
                    "id",
                    f"id {item.id!r} is not a stable identifier",
                    [key, i, "id"],
                    [item.id],
                    hint="letters, digits, _ and -, starting with a letter; put free text in title",
                )
            if item.id in seen:
                out.add(
                    "error",
                    "duplicate-id",
                    f"id {item.id} is used by {seen[item.id]} and {key}",
                    [key, i, "id"],
                    [item.id],
                    hint="ids are unique across feeds, products, blocks, steps and streams",
                )
            seen.setdefault(item.id, key)
            for j, port in enumerate(getattr(item, "ports", []) or []):
                if not _ID.match(port.id):
                    out.add(
                        "error",
                        "id",
                        f"port id {item.id}.{port.id!r} is not a stable identifier",
                        [key, i, "ports", j],
                        [item.id],
                    )
    for i, block in enumerate(fs.blocks):
        if block.parent and out.process.kinds.get(block.parent) != "block":
            out.add(
                "error",
                "id",
                f"block {block.id} names parent {block.parent}, which is no block",
                ["blocks", i, "parent"],
                [block.id],
            )
            continue
        chain, at = [block.id], block.parent
        while at is not None and at not in chain:
            chain.append(at)
            at = out.process.home(at)
        if at is not None:
            out.add(
                "error",
                "parent",
                f"block {block.id} is in a parent cycle: {' -> '.join([*chain, at])}",
                ["blocks", i, "parent"],
                [block.id],
                hint="nested blocks form a tree: drop one of the parents",
            )
    for i, step in enumerate(fs.steps):
        if out.process.kinds.get(step.block) != "block":
            out.add(
                "error",
                "id",
                f"step {step.id} names block {step.block}, which does not exist",
                ["steps", i, "block"],
                [step.id],
                hint="every step belongs to a block of blocks:",
            )
    for i, block in enumerate(fs.blocks):
        _known_class(out, block.class_, block.method, ["blocks", i], block.id)
    for i, step in enumerate(fs.steps):
        _known_class(out, step.class_, step.method, ["steps", i], step.id)
        _known_symbol(out, step.symbol, ["steps", i, "symbol"], step.id)
    ids = [c.id for c in fs.cases]
    defaults = [c.id for c in fs.cases if c.default]
    if not fs.cases:
        out.add("error", "case", "no case declared", ["cases"], hint="cases: [{id: design}]")
    if len(set(ids)) != len(ids) or len(defaults) > 1:
        out.add(
            "error",
            "case",
            "case ids must be unique and at most one case the default",
            ["cases"],
        )


def _known_symbol(out: _Out, name: str | None, loc: list[Any], owner: str) -> None:
    from chemeascode.domains.process.symbols import BOX, JUNCTION, symbols

    if name is None or name in (JUNCTION, BOX) or name in symbols():
        return
    out.add(
        "warning",
        "symbol",
        f"{owner}: symbol {name} is not in the symbol library; the PFD draws its class's",
        loc,
        [owner],
        hint=f"{JUNCTION}, {BOX} or a symbol name, e.g. TANK_CONE_ROOF_SHAPE, MIXER_SHAPE "
        "(the list: src/chemeascode/domains/process/data/iso_shapes.json)",
    )


def _known_class(out: _Out, name: str, method: str | None, loc: list[Any], owner: str) -> None:
    from chemeascode.domains.process.build import method_enum, step_class, step_method

    cls = step_class(name)
    if cls is None:
        out.add(
            "error",
            "class",
            f"{owner}: {name} is not a DEXPI 2.0.1 process step class",
            [*loc, "class"],
            [owner],
            hint="e.g. ProcessStep, Compressing, Cooling, SeparatingByThermalProcess, Mixing",
        )
        return
    if method is None:
        return
    field_info = cls.model_fields.get("method")
    methods = method_enum(field_info.annotation) if field_info is not None else None
    if methods is None:
        out.add(
            "error",
            "class",
            f"{owner}: {name} has no DEXPI method, but method: {method} is given",
            [*loc, "method"],
            [owner],
            hint="drop method:, or choose a class that has one (e.g. Pumping, Cooling)",
        )
    elif step_method(field_info.annotation, method) is None:
        out.add(
            "error",
            "class",
            f"{owner}: {method} is not a {methods.__name__} of {name}",
            [*loc, "method"],
            [owner],
            hint="method: one of " + ", ".join(str(m.value) for m in methods),
        )


def _unit_rules(out: _Out) -> None:
    units = out.process.flowsheet.units
    if units.pressure not in PRESSURE_UNITS:
        out.add(
            "error",
            "unit",
            f"units.pressure {units.pressure!r} is not a pressure unit (absolute or gauge?)",
            ["units", "pressure"],
            hint="write kPa(a), bar(a) or MPa(a)",
        )
    elif PRESSURE_UNITS[units.pressure][1] == "gauge":
        out.add(
            "error",
            "gauge-default",
            f"units.pressure {units.pressure} is gauge: the default must be absolute",
            ["units", "pressure"],
            hint="use kPa(a); give a gauge value with an explicit unit: kPa(g) on the property",
        )
    if units.temperature not in TEMPERATURE_UNITS:
        out.add("error", "unit", f"units.temperature {units.temperature!r}", ["units"])
    if units.flow not in FLOW_UNITS:
        out.add(
            "error",
            "unit",
            f"units.flow {units.flow!r} is not one of {', '.join(FLOW_UNITS)}",
            ["units", "flow"],
        )
    if units.duty not in DUTY_UNITS:
        out.add("error", "unit", f"units.duty {units.duty!r}", ["units", "duty"])
    if units.enthalpy != "kJ/kmol":
        out.add("error", "unit", f"units.enthalpy {units.enthalpy!r}", ["units", "enthalpy"])
    for i, s in enumerate(out.process.flowsheet.streams):
        for case, state in s.state.items():
            for name, q in state.calculated.items():
                want = CALCULATED_UNITS.get(name)
                if want is None or q.unit is None or q.unit == want:
                    continue
                out.add(
                    "error",
                    "unit",
                    f"stream {s.id} ({case}): calculated {name} in {q.unit!r}, must be {want}",
                    ["streams", i, "state", case, "calculated", name, "unit"],
                    [s.id],
                    hint=f"give {name} in {want} (it is read as {want}, never converted)",
                )
    uses_normal = units.flow == "Nm3/h" or any(
        state.flow is not None and state.flow.unit == "Nm3/h"
        for s in out.process.flowsheet.streams
        for state in s.state.values()
    )
    if uses_normal and units.normal_conditions is None:
        out.add(
            "error",
            "normal-conditions",
            "a flow is in Nm3/h but units.normal_conditions is not given",
            ["units"],
            hint="units: {normal_conditions: {temperature: 273.15, pressure: 101.325, "
            "basis: ideal_gas}}",
        )
    uses_enthalpy = any(
        "enthalpy" in name
        for s in out.process.flowsheet.streams
        for st in s.state.values()
        for name in st.calculated
    )
    if uses_enthalpy and units.enthalpy_reference is None:
        out.add(
            "error",
            "enthalpy-reference",
            "an enthalpy is given but units.enthalpy_reference is not",
            ["units"],
            hint="units: {enthalpy_reference: {state: ideal_gas, temperature: 298.15}}",
        )


def _port_rules(out: _Out) -> None:
    process = out.process
    fs = process.flowsheet
    used: dict[tuple[str, str], str] = {}
    delegated: dict[tuple[str, str], str] = {}
    # step ports delegate a port of their block, nested block ports one of their parent
    owners = [("steps", i, s, s.block) for i, s in enumerate(fs.steps)]
    owners += [("blocks", i, b, b.parent) for i, b in enumerate(fs.blocks) if b.parent]
    for key_, i, step, owner in owners:
        for j, port in enumerate(step.ports):
            if not port.delegates:
                continue
            block = process.nodes.get(owner)
            target = (
                next((p for p in block.ports if p.id == port.delegates), None) if block else None
            )
            loc = [key_, i, "ports", j, "delegates"]
            if target is None:
                out.add(
                    "error",
                    "delegation",
                    f"{step.id}.{port.id} delegates {owner}.{port.delegates}, which is not "
                    f"a port of block {owner}",
                    loc,
                    [step.id],
                    hint=f"declare the port under blocks: {owner}: ports:",
                )
                continue
            if (target.direction, target.kind) != (port.direction, port.kind):
                out.add(
                    "error",
                    "delegation",
                    f"{step.id}.{port.id} ({port.direction} {port.kind}) delegates "
                    f"{owner}.{target.id} ({target.direction} {target.kind})",
                    loc,
                    [step.id],
                    hint="a delegate has its block port's direction and kind",
                )
            key = (owner, target.id)
            if key in delegated:
                out.add(
                    "error",
                    "port-reused",
                    f"{owner}.{target.id} is delegated by {delegated[key]} and {step.id}.{port.id}",
                    loc,
                    [step.id],
                )
            delegated[key] = f"{step.id}.{port.id}"
    for i, stream in enumerate(fs.streams):
        ends = process.ends(stream)
        for side, text, end, want in (
            ("from", stream.from_, ends[0], "out"),
            ("to", stream.to, ends[1], "in"),
        ):
            loc = ["streams", i, side]
            if end is None:
                out.add(
                    "error",
                    "port",
                    f"stream {stream.id} {side}: {text!r} is not NODE.port",
                    loc,
                    [stream.id],
                    hint="name a declared port: MAC.out",
                )
                continue
            if end.node not in process.kinds:
                out.add(
                    "error",
                    "port",
                    f"stream {stream.id} {side}: {end.node} is no feed, product, block or step",
                    loc,
                    [stream.id],
                )
                continue
            port = process.port(end)
            if port is None:
                out.add(
                    "error",
                    "port",
                    f"stream {stream.id} {side}: {end.node} has no port {end.port}",
                    loc,
                    [stream.id],
                    hint=f"declare it: ports: [{{id: {end.port}, direction: {want}}}]",
                )
                continue
            if port.direction != want or port.kind != stream.kind:
                out.add(
                    "error",
                    "port",
                    f"stream {stream.id} ({stream.kind}) {side} {text}: the port is "
                    f"{port.direction} {port.kind}",
                    loc,
                    [stream.id],
                    hint=f"a stream runs from an out port to an in port of its kind ({want})",
                )
            key = (end.node, end.port)
            if key in used:
                out.add(
                    "error",
                    "port-reused",
                    f"port {text} carries {used[key]} and {stream.id}",
                    loc,
                    [stream.id],
                    hint="one stream per port: declare another port",
                )
            used[key] = stream.id
            if key in delegated:
                out.add(
                    "error",
                    "port-reused",
                    f"stream {stream.id} ends at {text}, which {delegated[key]} delegates: the "
                    "stream would be counted twice",
                    loc,
                    [stream.id],
                    hint=f"end the stream at {delegated[key]} and keep its id",
                )
            other = ends[1] if side == "from" else ends[0]
            if other is not None and other.node in process.kinds:
                # up from the end to the innermost block holding both ends, port by port
                level = process.level(end.node, other.node)
                at = end
                for _ in process.kinds:  # bounded: a parent cycle is reported above
                    block = process.home(at.node)
                    if block == level or block is None:
                        break
                    at_port = process.port(at)
                    if at_port is None or not at_port.delegates:
                        what = "step port" if process.kinds[at.node] == "step" else "port"
                        out.add(
                            "error",
                            "delegation",
                            f"stream {stream.id} crosses block {block} at {what} "
                            f"{at.node}.{at.port}, which delegates no port of {block}",
                            loc,
                            [stream.id],
                            hint=f"give the port delegates: <port of {block}> (the block port "
                            "the stream ran to before the block was refined)",
                        )
                        break
                    at = End(block, at_port.delegates)
            if process.kinds[end.node] == "block" and process.inside(end.node):
                out.add(
                    "info",
                    "refine-pending",
                    f"stream {stream.id} still ends at block port {text}, and block {end.node} "
                    "has steps or nested blocks",
                    loc,
                    [stream.id],
                    hint="move the end to a step (or nested block) port that delegates "
                    f"{text}; the stream keeps its id",
                )
    for key in ("feeds", "products", "blocks", "steps"):
        for i, item in enumerate(getattr(fs, key)):
            for j, port in enumerate(item.ports):
                k = (item.id, port.id)
                if k not in used and k not in delegated and not port.delegates:
                    out.add(
                        "info",
                        "port-open",
                        f"port {item.id}.{port.id} carries no stream",
                        [key, i, "ports", j],
                        [item.id],
                    )
                if key == "feeds" and port.direction != "out":
                    out.add(
                        "error",
                        "port",
                        f"feed {item.id}.{port.id} is an in port",
                        [key, i, "ports", j],
                        [item.id],
                    )
                if key == "products" and port.direction != "in":
                    out.add(
                        "error",
                        "port",
                        f"product {item.id}.{port.id} is an out port",
                        [key, i, "ports", j],
                        [item.id],
                    )
                if port.delegates and key != "steps" and not getattr(item, "parent", None):
                    out.add(
                        "error",
                        "delegation",
                        f"{item.id}.{port.id}: only ports of steps and nested blocks delegate",
                        [key, i, "ports", j],
                        [item.id],
                    )


def _state_rules(out: _Out) -> None:
    process = out.process
    fs = process.flowsheet
    cases = {c.id for c in fs.cases}
    templates = process.templates()
    for i, stream in enumerate(fs.streams):
        if stream.kind == "material" and process.materials is not None:
            if not stream.template:
                out.add(
                    "warning",
                    "template",
                    f"material stream {stream.id} names no template",
                    ["streams", i],
                    [stream.id],
                    hint="template: <id from process/materials.yaml templates>",
                )
            elif stream.template not in templates:
                out.add(
                    "error",
                    "template",
                    f"stream {stream.id}: template {stream.template} is not in {MATERIALS_FILE}",
                    ["streams", i, "template"],
                    [stream.id],
                )
        for case, state in stream.state.items():
            base = ["streams", i, "state", case]
            if case not in cases:
                out.add(
                    "error",
                    "case",
                    f"stream {stream.id}: state for case {case}, which is not declared",
                    base,
                    [stream.id],
                    hint=f"declared cases: {', '.join(sorted(cases))}",
                )
            if state.pressure is not None:
                unit = state.pressure.unit or fs.units.pressure
                if unit not in PRESSURE_UNITS:
                    out.add(
                        "error",
                        "unit",
                        f"stream {stream.id} pressure unit {unit!r} is not absolute or gauge",
                        [*base, "pressure"],
                        [stream.id],
                        hint="kPa(a), bar(a), or kPa(g) for an explicit gauge value",
                    )
                elif PRESSURE_UNITS[unit][1] == "absolute" and state.pressure.value <= 0:
                    out.add(
                        "error",
                        "pressure",
                        f"stream {stream.id}: absolute pressure {state.pressure.value} {unit}",
                        [*base, "pressure"],
                        [stream.id],
                        hint="an absolute pressure is positive",
                    )
            if state.temperature is not None:
                unit = state.temperature.unit or fs.units.temperature
                kelvin = to_kelvin(state.temperature.value, unit)
                if kelvin is None:
                    out.add(
                        "error",
                        "unit",
                        f"stream {stream.id} temperature unit {unit!r}",
                        [*base, "temperature"],
                        [stream.id],
                        hint="K or °C",
                    )
                elif kelvin <= 0:
                    out.add(
                        "error",
                        "unit",
                        f"stream {stream.id}: temperature {kelvin} K",
                        [*base, "temperature"],
                        [stream.id],
                    )
            if state.flow is not None:
                unit = state.flow.unit or fs.units.flow
                if unit not in FLOW_UNITS:
                    out.add(
                        "error",
                        "unit",
                        f"stream {stream.id} flow unit {unit!r}",
                        [*base, "flow"],
                        [stream.id],
                        hint=", ".join(FLOW_UNITS),
                    )
                elif state.flow.basis and state.flow.basis != FLOW_UNITS[unit][0]:
                    out.add(
                        "error",
                        "basis",
                        f"stream {stream.id}: flow basis {state.flow.basis} but unit {unit} is "
                        f"{FLOW_UNITS[unit][0]}",
                        [*base, "flow"],
                        [stream.id],
                    )
                if stream.kind != "material":
                    out.add(
                        "error",
                        "unit",
                        f"{stream.kind} stream {stream.id} has a flow",
                        [*base, "flow"],
                        [stream.id],
                        hint="energy streams carry duty",
                    )
            if state.duty is not None:
                unit = state.duty.unit or fs.units.duty
                if unit not in DUTY_UNITS:
                    out.add(
                        "error",
                        "unit",
                        f"stream {stream.id} duty unit {unit!r}",
                        [*base, "duty"],
                        [stream.id],
                    )
            if state.composition is not None:
                comp = state.composition
                total = sum(comp.values.values())
                if abs(total - 1.0) > 1e-3:
                    out.add(
                        "error",
                        "composition-sum",
                        f"stream {stream.id}: {comp.basis} sum {total:.6g}, not 1",
                        [*base, "composition"],
                        [stream.id],
                        hint="fractions on the stated basis sum to 1 within 0.001",
                    )
                if any(v < 0 for v in comp.values.values()):
                    out.add(
                        "error",
                        "composition-sum",
                        f"stream {stream.id}: a negative fraction",
                        [*base, "composition"],
                        [stream.id],
                    )
                template = templates.get(stream.template or "")
                if template is not None:
                    for name in comp.values:
                        if name not in template.components:
                            out.add(
                                "error",
                                "component",
                                f"stream {stream.id}: component {name} is not in template "
                                f"{template.id}",
                                [*base, "composition", "values", name],
                                [stream.id],
                            )


def _balanced_cases(fs: Flowsheet) -> list[str]:
    """The cases whose balances the rules check: the default case, then every other declared
    case that some stream gives a state for (a case nobody has filled has nothing to check)."""
    default = fs.default_case()
    filled = {case for s in fs.streams for case in s.state}
    return [default] + [c.id for c in fs.cases if c.id != default and c.id in filled]


def _balance_rules(out: _Out) -> None:
    """The mass, component and element balances of every case (:func:`_balanced_cases`). An
    imbalance is an error in any case; the info findings (unsupported, not evaluable) are given
    for the default case only, so a flowsheet with several cases does not repeat them."""
    process = out.process
    fs = process.flowsheet
    default = fs.default_case()
    for case in _balanced_cases(fs):
        for result in balances(process, case):
            if case == default or result.status == "imbalance":
                _balance_finding(out, result, case)


def _balance_finding(out: _Out, result: Balance, case: str) -> None:
    """The finding of one mass balance (none for a balance that closes)."""
    fs = out.process.flowsheet
    key = "blocks" if result.kind == "block" else "steps"
    index = next(i for i, n in enumerate(getattr(fs, key)) if n.id == result.node)
    loc = [key, index]
    if result.status == "unsupported":
        out.add(
            "info",
            "balance-unsupported",
            f"{result.kind} {result.node}: balance not evaluated: unsupported scope "
            f"({', '.join(result.missing)})",
            loc,
            [result.node],
            hint="dynamic balances are not evaluated; use steady_state_nonreactive or reactive",
        )
    elif result.status == "not-evaluable":
        out.add(
            "info",
            "balance-not-evaluable",
            f"{result.kind} {result.node} ({case}): balance not evaluable, missing "
            f"{', '.join(result.missing[:6])}{', ...' if len(result.missing) > 6 else ''}",
            loc,
            [result.node],
            hint="give the missing values (provenance given or assumed)",
        )
    elif result.status == "imbalance":
        out.add(
            "error",
            "balance",
            f"{result.kind} {result.node} ({case}) does not balance: "
            + "; ".join(result.failing[:4]),
            loc,
            [result.node],
            hint=f"in: {', '.join(result.streams_in)}; out: {', '.join(result.streams_out)}"
            " -- correct the flows or compositions",
        )
    elif result.status == "ok" and result.missing:
        # its own rule id: the concept gate accepts it while the mass balance stays strict
        out.add(
            "info",
            "component-balance-not-evaluable",
            f"{result.kind} {result.node} ({case}): mass balances; component balance not "
            f"evaluable, missing {', '.join(result.missing[:6])}",
            loc,
            [result.node],
            hint="give the compositions (and molar masses) of its streams; the basic gate "
            "requires component balances",
        )


def _energy_rules(out: _Out) -> None:
    """Energy balances (:mod:`.energy`) of every case (:func:`_balanced_cases`) where the
    enthalpies are there: an imbalance where energy streams cross the boundary, and (default
    case only) a reference that does not allow the balance."""
    from chemeascode.domains.process.energy import balance_findings, energy_balances

    process = out.process
    default = process.flowsheet.default_case()
    for case in _balanced_cases(process.flowsheet):
        found = balance_findings(process, energy_balances(process, case), case)
        # as for the mass balances: the info findings for the default case only
        out.findings += [f for f in found if case == default or f.level != "info"]


def _terminal_rules(out: _Out) -> None:
    """A utility level on a terminal that is not a utility."""
    fs = out.process.flowsheet
    for key, items in (("feeds", fs.feeds), ("products", fs.products)):
        for i, t in enumerate(items):
            if t.utility is not None and t.category != "utility":
                out.add(
                    "error",
                    "terminal",
                    f"terminal {t.id} gives utility: but its category is "
                    f"{t.category or 'not given'}",
                    [key, i, "utility"],
                    [t.id],
                    hint="category: utility, or remove utility:",
                )


def _calculated_rules(out: _Out) -> None:
    from chemeascode.domains.process.props import stale

    process = out.process
    for i, stream in enumerate(process.flowsheet.streams):
        for case in stream.state:
            names = stale(process, stream, case)
            if names:
                out.add(
                    "warning",
                    "calculated-stale",
                    f"stream {stream.id} ({case}): calculated {', '.join(names)} no longer "
                    "match their inputs (temperature, pressure, composition, upstream streams, "
                    "simulation or method changed)",
                    ["streams", i, "state", case],
                    [stream.id],
                    hint="run cheme process propagate --fill (composition, flow), "
                    "cheme process simulate --fill (simulated values) or "
                    "cheme process props --fill; a state outside the method's range keeps "
                    "the old values and stays stale",
                )


def _tear_rules(out: _Out) -> None:
    """``cheme.process-tear``: a tear (``tears:``, ADR 0060) propagate cannot iterate."""
    from chemeascode.domains.process.recycle import tear_problems

    tears = out.process.flowsheet.tears
    for i, level, message in tear_problems(out.process):
        out.add(
            level,
            "tear",
            message,
            ["tears", i],
            [tears[i].stream],
            hint="tear a material stream between two steps of the loop (one per loop), its "
            "initial: in declared components, fractions that sum to 1 and a flow unit; a "
            "stream whose flow and composition are both design inputs is no tear",
        )


#: Link target -> (parsed list key, attribute of the list, attribute of an item).
LINK_LISTS = {
    "equipment": ("equipment", "equipment", "tag"),
    "line": ("lines", "lines", "number"),
    "instrument": ("instruments", "instruments", "tag"),
}


def link_problem(link: Any, lists: dict[str, Any], sheet_ids: set[str]) -> str | None:
    """Why *link* does not resolve against the lists and sheets, or None when it does.

    A ``sheet:`` scope must be a declared sheet, and an item the list places on another sheet
    does not resolve on this one."""
    if link.target == "sheet":
        return None if link.ref in sheet_ids else f"sheet {link.ref} is not declared in plant.yaml"
    key, attr, ident = LINK_LISTS[link.target]
    parsed = lists.get(key)
    if parsed is None:
        return f"no valid {link.target} list to resolve {link.ref} against"
    items = {str(getattr(e, ident)): e for e in getattr(parsed, attr, [])}
    item = items.get(link.ref)
    if item is None:
        return f"{link.target} {link.ref} is not in the {link.target} list"
    if link.sheet:
        if link.sheet not in sheet_ids:
            return f"sheet {link.sheet} is not declared in plant.yaml"
        placed = getattr(item, "sheet", None)
        if placed and placed != link.sheet:
            return f"{link.target} {link.ref} is on sheet {placed} per its list, not {link.sheet}"
    return None


def _link_rules(out: _Out, lists: dict[str, Any], sheet_ids: set[str]) -> None:
    fs = out.process.flowsheet
    for key in ("feeds", "products", "blocks", "steps", "streams"):
        for i, item in enumerate(getattr(fs, key)):
            for j, link in enumerate(item.links):
                problem = link_problem(link, lists, sheet_ids)
                if problem:
                    out.add(
                        "info",
                        "link-unresolved",
                        f"{item.id} links {link.target} {link.ref}: {problem}",
                        [key, i, "links", j],
                        [item.id],
                        hint="add it to the list, or correct the ref or sheet; the process-links "
                        "gate requires resolved links",
                    )
