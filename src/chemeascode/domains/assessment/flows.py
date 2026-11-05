"""The plant's feed and product rates: the flowsheet's terminals in one case.

:func:`terminals` sums, for every feed and product of the flowsheet, the streams that reach it:
a material terminal in kg/h (the mass flow, ``process.model.stream_flows``), an energy terminal in
kWh/h (the stream duties in kW). What a terminal lacks (a stream without flow or duty) or cannot
count (an unknown unit, a negative duty) is recorded on it, not raised. The LCA's inventory
(:mod:`.lca.inventory`) and the TEA (:mod:`.tea`) read the same rates.

:func:`boundary_gaps` says what those rates leave out (it changes nothing about them): the
boundaries the flowsheet implies but does not declare. Rules (``cheme.boundary-*``):

- ``boundary-utility-unassigned`` (warning): a step that exchanges heat or work by its class or
  reactions (heater, cooler, compressor, pump, column, reactor) with no energy stream: its
  steam, cooling, refrigeration or power is in no terminal, so no inventory counts it (a
  reactor declared adiabatic, by ``mode: adiabatic`` in process/simulation.yaml or a bed with
  ``heat: adiabatic``, is not one);
- ``boundary-unclassified``: a terminal without ``category`` (warning for a product, where
  wastewater, off-gas, solid waste or an emission would go unnoticed; info for a feed);
- ``boundary-energy-terminal`` (info): an energy terminal whose category is not ``utility``;
- ``boundary-utility-level`` (info): a utility terminal serving heat without ``utility:``
  temperatures, so ``cheme process simulate`` cannot check its level;
- ``boundary-adiabatic-unread``: process/simulation.yaml does not load, so ``mode: adiabatic``
  there is not read (warning, naming them, when a reactor is reported unassigned that such a
  declaration could exempt; info otherwise).

What it does not check (:data:`NOT_CHECKED`): steps of other unit kinds (component separators,
flash drums, mixers, splitters, unknown classes), whether an energy stream at a step reaches a
utility terminal (a step-to-step stream counts as connected), and whether duties are given or
balance (``cheme process energy``). No gap found is not a complete inventory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.process.model import Process, stream_flows
from chemeascode.domains.process.schema import CALCULATED_UNITS, DUTY_UNITS
from chemeascode.foundation.uncertainty import Uncertainty


def common(values: list[Any]) -> Any:
    """The one value every entry of *values* gives, if they all give the same; else None."""
    first = values[0] if values else None
    return first if all(v == first for v in values) else None


@dataclass
class Terminal:
    """A feed or product of the flowsheet in one case: the sum of the streams that reach it
    (kg/h for material, kWh/h for energy), with the provenance of the values summed."""

    key: str
    title: str
    direction: str
    per_hour: float = 0.0
    kinds: set[str] = field(default_factory=set)
    components: dict[str, float] = field(default_factory=dict)
    provenance: list[str] = field(default_factory=list)
    #: The ``origin`` of each value in ``provenance`` (None where it gives none).
    origins: list[str | None] = field(default_factory=list)
    streams: list[str] = field(default_factory=list)
    #: What the total lacks (a stream without flow or duty).
    missing: list[str] = field(default_factory=list)
    #: Why the total cannot be split into components (composition, molar masses).
    unsplit: list[str] = field(default_factory=list)
    #: Values that cannot be counted at all (unknown unit, negative duty).
    invalid: list[str] = field(default_factory=list)
    #: The exergy flow, kJ/h, of the streams with a calculated exergy; and the streams without.
    exergy: float = 0.0
    no_exergy: list[str] = field(default_factory=list)
    #: Streams whose calculated exergy is stale (their inputs changed since): not used.
    stale_exergy: list[str] = field(default_factory=list)
    #: The ``uncertainty`` of every flow or duty summed (None where it gives none).
    uncertainties: list[Uncertainty | None] = field(default_factory=list)

    @property
    def uncertainty(self) -> Uncertainty | None:
        """The uncertainty of the total: the one every summed value gives, if they all give
        the same; else None (the study's default for the provenance applies)."""
        return common(self.uncertainties)

    @property
    def origin(self) -> str | None:
        """The origin of the total: the one every summed value gives, if they all give the
        same; else None."""
        return common(self.origins)

    @property
    def kind(self) -> str:
        return "energy" if self.kinds == {"energy"} else "material"


def terminals(process: Process, case: str) -> list[Terminal]:
    """Every feed and product of *case* with its summed flow."""
    fs = process.flowsheet
    feeds = {n.id: Terminal(f"feed:{n.id}", n.title or n.id, "input") for n in fs.feeds}
    products = {n.id: Terminal(f"product:{n.id}", n.title or n.id, "output") for n in fs.products}
    for stream in fs.streams:
        if stream.kind == "information":
            continue
        ends = [
            feeds.get(stream.from_.split(".")[0]),
            products.get(stream.to.split(".")[0]),
        ]
        for terminal in (t for t in ends if t is not None):
            add_stream(process, case, stream, terminal)
    return [*feeds.values(), *products.values()]


def add_stream(process: Process, case: str, stream, terminal: Terminal) -> None:
    """Add *stream* in *case* to *terminal*."""
    fs = process.flowsheet
    terminal.streams.append(stream.id)
    terminal.kinds.add(stream.kind)
    state = stream.state.get(case)
    if stream.kind == "energy":
        if state is None or state.duty is None:
            terminal.missing.append(f"{stream.id} duty")
            return
        unit = state.duty.unit or fs.units.duty
        if unit not in DUTY_UNITS:
            terminal.invalid.append(
                f"{stream.id} duty unit {unit!r} (one of {', '.join(DUTY_UNITS)})"
            )
            return
        if state.duty.value < 0:
            terminal.invalid.append(
                f"{stream.id} duty {state.duty.value:g} {unit} (negative: give the stream the "
                "direction the energy flows)"
            )
            return
        terminal.per_hour += state.duty.value * DUTY_UNITS[unit]
        terminal.provenance.append(state.duty.provenance)
        terminal.origins.append(state.duty.origin)
        terminal.uncertainties.append(state.duty.uncertainty)
        return
    flows = stream_flows(process, stream, case)
    if flows.total is None:
        terminal.missing += flows.missing
        return
    terminal.per_hour += flows.total
    terminal.uncertainties.append(state.flow.uncertainty if state and state.flow else None)
    calculated = state.calculated if state else {}
    exergy, molar_mass = calculated.get("exergy"), calculated.get("molar_mass")
    from chemeascode.domains.process.props import stale

    old = set(stale(process, stream, case))
    if "exergy" in old or "molar_mass" in old:
        terminal.stale_exergy.append(stream.id)
        terminal.no_exergy.append(stream.id)
    elif (
        exergy is not None
        and molar_mass is not None
        and molar_mass.value > 0
        # another unit is cheme.process-unit: never read as kJ/kmol and kg/kmol
        and exergy.unit in (None, CALCULATED_UNITS["exergy"])
        and molar_mass.unit in (None, CALCULATED_UNITS["molar_mass"])
    ):
        terminal.exergy += flows.total / molar_mass.value * exergy.value
    else:
        terminal.no_exergy.append(stream.id)
    terminal.provenance.append(state.flow.provenance if state and state.flow else "assumed")
    terminal.origins.append(state.flow.origin if state and state.flow else None)
    if state and state.composition:
        terminal.provenance.append(state.composition.provenance)
        terminal.origins.append(state.composition.origin)
    if flows.components is None:
        terminal.unsplit += flows.missing or [f"{stream.id} composition"]
    for name, value in (flows.components or {}).items():
        terminal.components[name] = terminal.components.get(name, 0.0) + value


# -- boundary completeness ----------------------------------------------------------------------

#: Unit operations (``process.simulation.translate.unit_of``) that exchange heat or work.
STEP_DUTY_UNITS = (
    "compressor",
    "pump",
    "heater",
    "cooler",
    "shortcut_column",
    "conversion_reactor",
    "equilibrium_reactor",
    "gibbs_reactor",
)
#: What :func:`boundary_gaps` checks and what it does not, as the reports state it.
#: The rules whose breach is a warning (a gap: ``complete`` is False).
CHECKED = (
    "steps of the unit kinds "
    + ", ".join(STEP_DUTY_UNITS)
    + " have an energy stream at a port (or are declared adiabatic)",
    "every product terminal has a category",
)
#: The rules whose breach is only noted (info: ``complete`` stays True).
NOTED = (
    "every feed terminal has a category",
    "energy terminals are classified utility; heat utilities declare a kind and supply temperature",
)
NOT_CHECKED = (
    "steps of other unit kinds (component separators, flash drums, mixers, splitters, "
    "unknown classes)",
    "whether a step's energy stream reaches a utility terminal (a step-to-step stream counts)",
    "whether duties are given or balance (cheme process energy)",
)
#: Utility kinds that carry heat (their temperature level matters).
HEAT_UTILITIES = ("steam", "hot_oil", "fired_heat", "cooling_water", "air_cooling", "refrigerant")


@dataclass
class BoundaryReport:
    """What the flowsheet's declared boundary leaves out (:func:`boundary_gaps`)."""

    #: category -> terminal ids; ``unclassified`` for those without one.
    categories: dict[str, list[str]] = field(default_factory=dict)
    #: Steps that exchange heat or work with no energy stream.
    unassigned_duties: list[str] = field(default_factory=list)
    findings: list[Any] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """No warning: no gap found *by these rules* (:data:`CHECKED`); it does not mean the
        inventory is complete (:data:`NOT_CHECKED`)."""
        return not any(f.level in ("warning", "error") for f in self.findings)

    def entry(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "categories": self.categories,
            "unassigned_duties": self.unassigned_duties,
        }

    def payload(self) -> dict[str, Any]:
        """:meth:`entry` with the rules (``checked`` warn, ``noted`` are info only,
        ``not_checked``) and the gaps by rule, as the TEA and LCA reports give it."""
        return {
            **self.entry(),
            "checked": list(CHECKED),
            "noted": list(NOTED),
            "not_checked": list(NOT_CHECKED),
            "gaps": [
                {
                    "rule": f.rule,
                    "level": f.level,
                    "ids": f.ids,
                    "message": f.message,
                    "file": f.file,
                    "line": f.line,
                }
                for f in self.findings
            ],
        }

    def coverage_lines(self) -> list[str]:
        """Markdown: whether the check found gaps, and what it checks, notes and does not."""
        lines = [
            "No warning from the boundary check, whose warnings are that:"
            if self.complete
            else "**Gaps found** by the boundary check, whose warnings are that:"
        ]
        lines += ["", *[f"- {c} (warning when not)" for c in CHECKED]]
        lines += ["", "It notes (info, not a gap):", "", *[f"- {c}" for c in NOTED]]
        lines += ["", "It does not check:", "", *[f"- {c}" for c in NOT_CHECKED]]
        return lines

    def table_lines(self) -> list[str]:
        """Markdown: the findings by rule, level, ids and location (none: no lines)."""
        if not self.findings:
            return []
        lines = ["", "| rule | level | ids | where |", "|---|---|---|---|"]
        for f in self.findings:
            where = f"{f.file}:{f.line}" if f.line else f.file
            lines.append(f"| {f.rule} | {f.level} | {', '.join(f.ids)} | {where} |")
        return lines


def _energy_connected(process: Process, step: Any, ends: set[str]) -> bool:
    """Whether an energy stream reaches *step*, at its own port or at a block port one of its
    energy ports delegates to (through every level)."""
    for port in step.ports:
        if port.kind != "energy":
            continue
        node, name = step, port.id
        while node is not None:
            if f"{node.id}.{name}" in ends:
                return True
            port_of = next((p for p in node.ports if p.id == name), None)
            if port_of is None or not port_of.delegates:
                break
            parent = getattr(node, "block", None) or getattr(node, "parent", None)
            node, name = process.nodes.get(parent or ""), port_of.delegates
    return False


def _machines_only(process: Process, nodes: list[str]) -> bool:
    """Whether every node served is a compressor or pump (its energy stream is power)."""
    from chemeascode.domains.process.simulation.translate import unit_of

    for n in nodes:
        node = process.nodes.get(n)
        if node is None or unit_of(getattr(node, "class_", "") or "") not in ("compressor", "pump"):
            return False
    return True


def _adiabatic(process: Process) -> tuple[set[str], list[Any]]:
    """Steps declared adiabatic: a reactor with ``mode: adiabatic`` in process/simulation.yaml,
    or a catalyst bed with ``heat: adiabatic``; with the findings of a simulation.yaml that
    does not load."""
    from chemeascode.domains.process.simulation.translate import load

    found = {
        s.id
        for s in process.flowsheet.steps
        if any(
            getattr(getattr(s, name, None), "heat", None) == "adiabatic"
            for name in ("bed", "tank", "batch")
        )
    }
    sim, _, problems = load(process.root)
    if sim is not None:
        found |= {uid for uid, spec in sim.specs.items() if spec.mode == "adiabatic"}
    return found, problems


def boundary_gaps(process: Process) -> BoundaryReport:
    """The boundary-completeness findings of the flowsheet (see the module docstring); the
    terminal rates (:func:`terminals`) are not touched."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.simulation.translate import reactor_unit, unit_of
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    fs = process.flowsheet
    report = BoundaryReport()

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        report.findings.append(
            Finding(
                FLOWSHEET_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.boundary-{rule}",
                message,
                line=_yaml_line(process.flowsheet_doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    lists = (("feeds", fs.feeds), ("products", fs.products))
    for key, items in lists:
        for i, t in enumerate(items):
            report.categories.setdefault(t.category or "unclassified", []).append(t.id)
            if t.category is not None:
                continue
            product = key == "products"
            add(
                "warning" if product else "info",
                "unclassified",
                f"{'product' if product else 'feed'} {t.id} ({t.title or t.id}) has no category: "
                "the TEA and LCA cannot tell "
                + (
                    "a product from wastewater, off-gas, solid waste or an emission"
                    if product
                    else "a raw material from a utility"
                ),
                [key, i],
                [t.id],
                "category: "
                + (
                    "product | by_product | wastewater | off_gas | solid_waste | emission | utility"
                    if product
                    else "raw_material | utility"
                ),
            )

    ends = {e for s in fs.streams if s.kind == "energy" for e in (s.from_, s.to)}
    inlets: dict[str, int] = {}
    for s in fs.streams:
        if s.kind == "material":
            node = s.to.split(".")[0]
            inlets[node] = inlets.get(node, 0) + 1
    adiabatic, unread = _adiabatic(process)
    reactors: list[str] = []  # reported unassigned, and mode: adiabatic could exempt them
    for i, step in enumerate(fs.steps):
        reacting = reactor_unit(step)
        if getattr(step, "reactor", None) in ("cstr", "batch", "semibatch"):
            reacting = "conversion_reactor"  # what DWSIM sees of a coupled tank: it has a duty
        unit = reacting or unit_of(step.class_, inlets.get(step.id, 1))
        if unit not in STEP_DUTY_UNITS or step.id in adiabatic:
            continue
        if _energy_connected(process, step, ends):
            continue
        report.unassigned_duties.append(step.id)
        if unit.endswith("_reactor"):
            reactors.append(step.id)
        add(
            "warning",
            "utility-unassigned",
            f"step {step.id} ({step.class_}{', reacting' if reacting else ''}) exchanges heat or "
            "work but no energy stream connects it to a utility: its steam, cooling, "
            "refrigeration or power is in no inventory",
            ["steps", i],
            [step.id],
            "give the step an energy port and a stream to a utility terminal (category: "
            "utility), or declare it adiabatic: mode: adiabatic in process/simulation.yaml "
            "(a reactor) or heat: adiabatic on its bed, tank or batch",
        )
    for problem in unread[:1]:
        first = problem.message.splitlines()[0]
        report.findings.append(
            Finding(
                problem.file,
                "warning" if reactors else "info",
                "cheme.boundary-adiabatic-unread",
                f"{problem.file} does not load ({first}): mode: adiabatic there is not read"
                + (
                    f", so reactors {', '.join(reactors)} may be reported unassigned only for that"
                    if reactors
                    else "; no step reported here depends on it"
                ),
                line=problem.line,
                ids=reactors,
                hint=f"correct {problem.file} (cheme validate names the line)",
            )
        )

    terminals = {t.id: t for t in [*fs.feeds, *fs.products]}
    served: dict[str, list[str]] = {}
    for s in fs.streams:
        if s.kind != "energy":
            continue
        for end, other in ((s.from_, s.to), (s.to, s.from_)):
            t = terminals.get(end.split(".")[0])
            if t is not None:
                served.setdefault(t.id, []).append(other.split(".")[0])
    for key, items in lists:
        for i, t in enumerate(items):
            if t.id not in served or t.category is None:
                continue
            if t.category != "utility":
                add(
                    "info",
                    "energy-terminal",
                    f"energy terminal {t.id} is classified {t.category}, not utility",
                    [key, i],
                    [t.id],
                    "category: utility, with utility: {kind: ...}",
                )
                continue
            level = t.utility
            heat = level.kind in HEAT_UTILITIES if level is not None else True
            if heat and (level is None or level.supply_temperature is None):
                if level is None and _machines_only(process, served[t.id]):
                    continue  # power for machines: no temperature level
                add(
                    "info",
                    "utility-level",
                    f"utility {t.id} serves {', '.join(sorted(set(served[t.id])))} without a "
                    "declared kind and supply temperature: its level is not checked",
                    [key, i],
                    [t.id],
                    "utility: {kind: steam, supply_temperature: {value: ..., provenance: given}}",
                )
    return report
