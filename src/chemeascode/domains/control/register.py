"""The control records against each other and against the plant (``cheme validate``).

``control/loops.yaml``, ``control/sequences.yaml``, the front matter of ``process/narrative.md``
and ``control/philosophy.md`` are checked against the lists and P&IDs (tags), the cause and
effect list (interlock ids), the flowsheet (operating cases, blocks, stream values) and each
other (loop, sequence, step and section ids). The rules:

- ``cheme.control-duplicate`` (error): a loop, sequence, step, section, objective or failure
  id given twice;
- ``cheme.control-document`` (error): front matter that is not valid (documents.py);
- ``cheme.control-cycle`` (error): loops whose setpoints depend on each other (cascade links
  in a ring), or a loop linked to itself. Ratio, override and feedforward links follow a
  measurement or select between outputs and may form rings;
- ``cheme.control-unknown-tag`` (warning): a tag in no list and on no sheet;
- ``cheme.control-ref`` (warning): a loop, sequence, step, interlock, case, section, block or
  stream that does not exist;
- ``cheme.control-conflict`` (warning): definitions that contradict each other: two loops
  driving one final element without an override between them, a setpoint outside its own
  limits, a mode the loop does not have, a split range without a range on every element;
- ``cheme.control-unit`` (warning): a value without a unit, or with one that does not fit what
  it measures (a pressure without (a)/(g), a delay or timeout that is not a time, here and in
  the interlocks' ``delay`` and ``logic``);
- ``cheme.control-case`` (warning): a target that names a stream value of an operating case
  and differs from it;
- ``cheme.control-unreachable`` (warning): a sequence step no path reaches;
- ``cheme.control-incomplete`` (info): something a complete record has and this one does not
  yet (a loop without a measurement, final element, action, fail position or target; a step
  without a completion condition; an alarm without an operator response; a sequence without
  abort behaviour). A stage gate decides when these must be gone;
- ``cheme.control-unresolved`` (info): an open point the record states (``unresolved``);
- ``cheme.control-logic-text`` (info): logic given as ``text``, which is not interpreted;
- ``cheme.control-shared-element`` (info): a loop measures or moves a tag of an interlock, so
  the loop is not independent of it. Nothing is concluded from it: independence and SIL stay
  the HAZOP's and the SIL study's;
- ``cheme.control-alarm-trip`` (info): an alarm at a high-high or low-low condition, which is
  a trip and belongs in the cause and effect list;
- ``cheme.control-stale`` (info): an entry of ``basis:`` changed since the revision recorded.

Prose is not checked for meaning. Tags are not checked while a sheet fails to load or a list
is invalid, and not at all when the repository has neither a list nor a sheet; references to
loops or sequences are not checked while their file is invalid, sections not without a valid
narrative.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from chemeascode.domains.control.documents import PHILOSOPHY_HEADINGS, Document, load_documents
from chemeascode.foundation.findings import Finding, Level
from chemeascode.foundation.workspace import LIST_FILES, Workspace
from chemeascode.foundation.yamlsource import _compose, _yaml_line

Loc = tuple[Any, ...]

#: Units of time read without Pint, in seconds.
_TIME_UNITS = {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}
#: Reference units a flow and a level may be converted to (any one fits).
_REFERENCE = {
    "flow": ("kg/h", "m**3/h", "kmol/h", "Nm3/h"),
    "level": ("m",),
}
#: Standard cubic metres: flows of gas whose reference state (15 °C, 20 °C, 60 °F) the unit does
#: not say, so they convert to nothing.
_STANDARD_VOLUME = re.compile(r"^Sm(3|³)/")
#: A relative difference above this between a target (a flow, a pressure) and its case value
#: is a mismatch.
CASE_TOLERANCE = 0.005
#: A temperature target further than this from its case value is a mismatch, K.
TEMPERATURE_TOLERANCE = 0.5
_TRIP = re.compile(r"(HH|LL)$")


def _slug(text: str) -> str:
    """*text* as a short id part: ``no-measurement``."""
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:48]


def walk(condition: Any, loc: Loc = ()) -> Iterator[tuple[Any, Loc]]:
    """Every condition in *condition* (itself first), with its location below *loc*."""
    if condition is None:
        return
    yield condition, loc
    for key, children in (("all", condition.all_), ("any", condition.any_)):
        for i, child in enumerate(children or []):
            yield from walk(child, (*loc, key, i))
    if condition.vote is not None:
        for i, child in enumerate(condition.vote.of):
            yield from walk(child, (*loc, "vote", "of", i))


class _Source:
    """A file the findings point into."""

    def __init__(self, name: str, node: Any, offset: int = 0) -> None:
        self.name = name
        self.node = node
        self.offset = offset

    def line(self, loc: Loc) -> int | None:
        found = _yaml_line(self.node, loc) if self.node is not None else None
        return found + self.offset if found else None


class _Checker:
    def __init__(
        self,
        workspace: Workspace,
        sheets: dict[str, Any],
        parsed: dict[str, Any],
        partial: bool,
        documents: dict[str, Document],
    ) -> None:
        from chemeascode.domains.control.interlocks import known_tags

        self.workspace = workspace
        self.findings: list[Finding] = []
        kinds = ("equipment", "instruments", "piping_items", "lines")
        has_lists = any(k in parsed for k in kinds)
        #: A list that exists but does not parse (validate reports it): its tags are unknown.
        invalid = any(workspace.list_file(k) is not None and k not in parsed for k in kinds)
        unchecked = partial or invalid or not (sheets or has_lists)
        self.tags = None if unchecked else known_tags(sheets, parsed)
        #: In file order, duplicates included; by id, the first of each.
        self.raw_loops = list(getattr(parsed.get("loops"), "loops", []))
        self.raw_sequences = list(getattr(parsed.get("sequences"), "sequences", []))
        self.loops = {}
        for loop in self.raw_loops:
            self.loops.setdefault(loop.id, loop)
        self.sequences = {}
        for sequence in self.raw_sequences:
            self.sequences.setdefault(sequence.id, sequence)
        #: Kinds whose file exists but does not parse: references to them are not checked.
        self.invalid = {
            k
            for k in ("loops", "sequences")
            if workspace.list_file(k) is not None and k not in parsed
        }
        model = parsed.get("interlocks")
        self.interlock_file = workspace.list_file("interlocks") is not None
        self.interlocks = {i.id: i for i in model.interlocks} if model is not None else None
        #: The C&E list exists but is invalid (validate reports it): its ids are unknown.
        self.interlocks_unknown = self.interlocks is None and self.interlock_file
        narrative = documents.get("narrative")
        self.sections = (
            {s.id for s in narrative.front.sections}
            if narrative is not None and narrative.front is not None
            else None
        )
        self.process = self._process()
        if self.process is not None:
            flowsheet = self.process.flowsheet
            self.cases: set[str] | None = {c.id for c in flowsheet.cases}
            self.nodes: set[str] | None = {n.id for n in [*flowsheet.blocks, *flowsheet.steps]}
            self.streams = {s.id: s for s in flowsheet.streams}
        else:
            self.cases = self.nodes = None
            self.streams = {}

    def _process(self) -> Any:
        from chemeascode.domains.process.model import has_process, load

        if not has_process(self.workspace.root):
            return None
        try:
            process, findings = load(self.workspace.root)
        except Exception:  # noqa: BLE001 - validate reports what is wrong with the process files
            return None
        if process is None or any(f.level == "error" for f in findings):
            return None
        return process

    # -- reporting -------------------------------------------------------------------------

    def add(
        self,
        source: _Source,
        level: Level,
        rule: str,
        message: str,
        loc: Loc,
        ids: list[str],
        hint: str,
        key: str = "",
    ) -> None:
        self.findings.append(
            Finding(
                source.name,
                level,
                rule,
                message,
                line=source.line(loc),
                ids=ids,
                hint=hint,
                key=key or ".".join(str(p) for p in loc),
            )
        )

    def incomplete(self, source: _Source, owner: str, what: str, loc: Loc, hint: str) -> None:
        """A draft gap; its key names the gap, so that each gap of one entry has its own id."""
        key = ".".join(str(p) for p in loc) + ":" + _slug(what)
        message = f"{owner}: {what}"
        self.add(source, "info", "cheme.control-incomplete", message, loc, [owner], hint, key)

    def unresolved(self, source: _Source, owner: str, items: list[str], loc: Loc) -> None:
        for i, text in enumerate(items):
            self.add(
                source,
                "info",
                "cheme.control-unresolved",
                f"{owner}: open point: {text}",
                (*loc, i),
                [owner],
                "resolve it and remove the entry, or keep it while it is open",
            )

    # -- references ------------------------------------------------------------------------

    def tag(self, source: _Source, owner: str, tag: str, loc: Loc) -> None:
        if self.tags is None or tag.strip() in self.tags:
            return
        self.add(
            source,
            "warning",
            "cheme.control-unknown-tag",
            f"{owner}: {tag} is in no list and on no sheet",
            loc,
            [owner, tag],
            "fix the tag (as printed on the P&ID), or list / draw the item",
        )

    def ref(self, source: _Source, owner: str, kind: str, value: str, loc: Loc) -> None:
        known: set[str] | None
        where = {
            "loop": LIST_FILES["loops"],
            "sequence": LIST_FILES["sequences"],
            "interlock": LIST_FILES["interlocks"],
            "case": "process/flowsheet.yaml cases",
            "section": "process/narrative.md sections",
            "block": "process/flowsheet.yaml blocks and steps",
            "stream": "process/flowsheet.yaml streams",
        }[kind]
        if kind in ("loop", "sequence") and f"{kind}s" in self.invalid:
            return
        if kind == "loop":
            known = set(self.loops)
        elif kind == "sequence":
            known = set(self.sequences)
        elif kind == "interlock":
            if self.interlocks_unknown:
                return
            known = set(self.interlocks or {})
        elif kind == "case":
            known = self.cases
        elif kind == "section":
            known = self.sections
        elif kind == "block":
            known = self.nodes
        else:
            known = set(self.streams) if self.process is not None else None
        if known is None or value in known:
            return
        missing = kind == "interlock" and not self.interlock_file
        self.add(
            source,
            "warning",
            "cheme.control-ref",
            f"{owner}: {kind} {value} is not in {where}"
            + (" (the plant has no such file)" if missing else ""),
            loc,
            [owner, value],
            f"fix the id, or add the {kind} to {where.split(' ')[0]}",
        )

    def condition(
        self, source: _Source, owner: str, condition: Any, loc: Loc, steps: set[str] | None = None
    ) -> None:
        for item, where in walk(condition, loc):
            if item.tag:
                self.tag(source, owner, item.tag, (*where, "tag"))
            for kind in ("loop", "interlock", "sequence"):
                value = getattr(item, kind)
                if value:
                    self.ref(source, owner, kind, value, (*where, kind))
            if item.step and steps is not None and item.step not in steps:
                self.add(
                    source,
                    "warning",
                    "cheme.control-ref",
                    f"{owner}: step {item.step} is not a step of the sequence",
                    (*where, "step"),
                    [owner, item.step],
                    "name a step of the same sequence",
                )
            if item.step and steps is None:
                self.add(
                    source,
                    "warning",
                    "cheme.control-ref",
                    f"{owner}: a step ({item.step}) is named outside a sequence",
                    (*where, "step"),
                    [owner, item.step],
                    "name the sequence instead (sequence: <id>, state: complete)",
                )
            named = item.tag or item.loop or item.interlock or item.sequence or item.step
            if named and not item.state.strip():
                self.incomplete(
                    source,
                    owner,
                    f"the condition on {named} has no state",
                    where,
                    "give the state that must hold (LAH, running, closed, in auto, ...)",
                )
            if item.text is not None:
                self.add(
                    source,
                    "info",
                    "cheme.control-logic-text",
                    f"{owner}: logic given as text is not checked: {item.text}",
                    (*where, "text"),
                    [owner],
                    "write it with all/any/vote and items where the format can express it",
                )
            if item.unresolved is not None:
                self.add(
                    source,
                    "info",
                    "cheme.control-unresolved",
                    f"{owner}: condition not known yet: {item.unresolved}",
                    (*where, "unresolved"),
                    [owner],
                    "state the condition once it is known",
                )
            if item.delay is not None:
                self.time(source, owner, item.delay, (*where, "delay"))

    def time(self, source: _Source, owner: str, amount: Any, loc: Loc) -> None:
        if not_a_time(amount.unit):
            self.add(
                source, *_time_finding(owner, amount.unit), (*loc, "unit"), [owner], _TIME_HINT
            )

    # -- values ----------------------------------------------------------------------------

    def target(
        self,
        source: _Source,
        owner: str,
        target: Any,
        loc: Loc,
        variable: str | None,
        cases: list[str],
        label: str | None = None,
    ) -> None:
        """*label*: what the target is called in messages (default its kind: setpoint, ...)."""
        if label is not None:
            target = target.model_copy(update={"kind": label})
        for i, case in enumerate(target.cases):
            self.ref(source, owner, "case", case, (*loc, "cases", i))
        if target.stream is not None:
            self.ref(source, owner, "stream", target.stream, (*loc, "stream"))
        if target.value is None:
            if target.unresolved is None:
                self.incomplete(
                    source,
                    owner,
                    f"the {target.kind} has no value",
                    loc,
                    "give the value with its unit and provenance, or say in unresolved why it "
                    "is not known yet",
                )
            else:
                self.add(
                    source,
                    "info",
                    "cheme.control-unresolved",
                    f"{owner}: {target.kind} not known yet: {target.unresolved}",
                    (*loc, "unresolved"),
                    [owner],
                    "give the value once it is known",
                )
            return
        if target.provenance is None:
            self.add(
                source,
                "warning",
                "cheme.control-unit",
                f"{owner}: the {target.kind} {target.value:g} has no provenance",
                (*loc, "value"),
                [owner],
                "add provenance (given, assumed or calculated) and its source",
                key=".".join(map(str, loc)) + ":provenance",
            )
        elif target.origin is not None:
            from chemeascode.foundation.schema_base import ORIGIN_CLASSES

            if target.provenance not in ORIGIN_CLASSES[target.origin]:
                self.add(
                    source,
                    "warning",
                    "cheme.provenance-origin",
                    f"{owner}: origin {target.origin} does not refine provenance "
                    f"{target.provenance}",
                    (*loc, "origin"),
                    [owner],
                    "see docs/framework/contract.md (Values)",
                )
        if not target.unit:
            self.add(
                source,
                "warning",
                "cheme.control-unit",
                f"{owner}: the {target.kind} {target.value:g} has no unit",
                (*loc, "value"),
                [owner],
                "give its unit (%, kg/h, °C, bar(g), ...)",
                key=".".join(map(str, loc)) + ":unit",
            )
            return
        problem = unit_problem(target.unit, variable)
        if problem:
            self.add(
                source,
                "warning",
                "cheme.control-unit",
                f"{owner}: {problem}",
                (*loc, "unit"),
                [owner],
                "give a unit of what the loop controls; pressures with (a) or (g)",
            )
            return
        if target.stream is not None and target.property is not None:
            self.case_value(source, owner, target, loc, cases)

    def case_value(
        self, source: _Source, owner: str, target: Any, loc: Loc, cases: list[str]
    ) -> None:
        from chemeascode.foundation.units import UnitError, convert_units, pressure_kind

        stream = self.streams.get(target.stream)
        if stream is None or self.process is None:
            return
        flowsheet = self.process.flowsheet
        for case in target.cases or cases or [flowsheet.default_case()]:
            if self.cases is not None and case not in self.cases:
                continue  # cheme.control-ref names it
            state = stream.state.get(case)
            quantity = getattr(state, target.property, None) if state is not None else None
            if quantity is None:
                self.add(
                    source,
                    "info",
                    "cheme.control-case",
                    f"{owner}: stream {stream.id} has no {target.property} in case {case} to "
                    "compare with",
                    (*loc, "stream"),
                    [owner, stream.id],
                    "fill the stream (cheme process propagate / simulate --fill), or drop the "
                    "stream link",
                    key=f"{'.'.join(map(str, loc))}:{case}",
                )
                continue
            unit = quantity.unit or getattr(flowsheet.units, target.property)
            # A temperature within TEMPERATURE_TOLERANCE (K), which does not depend on the
            # unit's zero point; a pressure relative to kPa of its own kind (absolute or
            # gauge); a flow relative, in the target's unit.
            if target.property == "pressure":
                gauge = pressure_kind(target.unit)[1] == "gauge"
                base = "kPa(g)" if gauge else "kPa(a)"
            else:
                base = {"temperature": "K"}.get(target.property)
            try:
                value = convert_units(quantity.value, unit, target.unit)
                if base is None:
                    a, b = value, target.value
                else:
                    a = convert_units(quantity.value, unit, base)
                    b = convert_units(target.value, target.unit, base)
            except UnitError as failure:
                self.add(
                    source,
                    "info",
                    "cheme.control-case",
                    f"{owner}: the {target.kind} in {target.unit} cannot be compared with stream "
                    f"{stream.id} {target.property} in case {case} ({unit}): {failure}",
                    (*loc, "unit"),
                    [owner, stream.id],
                    "give the target in a unit the case value converts to (a pressure of the "
                    "same kind, (a) or (g), as the case value)",
                    key=f"{'.'.join(map(str, loc))}:{case}",
                )
                continue
            if target.property == "temperature":
                if abs(a - b) <= TEMPERATURE_TOLERANCE:
                    continue
            elif abs(a - b) <= CASE_TOLERANCE * max(abs(a), abs(b)):
                continue
            self.add(
                source,
                "warning",
                "cheme.control-case",
                f"{owner}: the {target.kind} {target.value:g} {target.unit} differs from "
                f"stream {stream.id} {target.property} in case {case}, {value:.4g} "
                f"{target.unit}",
                (*loc, "value"),
                [owner, stream.id],
                "update the target to the case value, or drop the stream link when it is "
                "meant to differ",
                key=f"{'.'.join(map(str, loc))}:{case}",
            )

    # -- the files -------------------------------------------------------------------------

    def basis(self, source: _Source, owner: str, basis: list[Any]) -> None:
        from chemeascode.foundation.provenance import changed_since

        for i, entry in enumerate(basis):
            changed = changed_since(self.workspace.root, entry.path, entry.revision)
            if changed == []:
                continue
            what = (
                f"{', '.join(changed[:4])} changed since {entry.revision[:19]}"
                if changed
                else f"revision {entry.revision[:19]} of {entry.path} cannot be resolved here"
            )
            self.add(
                source,
                "info",
                "cheme.control-stale",
                f"{owner} {entry.relation} {entry.path}: {what}",
                ("basis", i),
                [entry.path],
                f"check the records against the current {entry.path}, then update the "
                "revision in basis",
            )


_TIME_HINT = "give the time in s, min or h"


def _time_finding(owner: str, unit: str) -> tuple[Level, str, str]:
    return "warning", "cheme.control-unit", f"{owner}: {unit!r} is not a unit of time"


def not_a_time(unit: str) -> bool:
    """Whether *unit* is known not to be a time (without Pint only s, ms, min and h are
    known; any other unit then passes)."""
    from chemeascode.foundation.units import UnitError, convert_units

    if unit in _TIME_UNITS:
        return False
    try:
        convert_units(1.0, unit, "s")
    except UnitError as failure:
        return "needs Pint" not in str(failure)
    return False


def unit_problem(unit: str, variable: str | None) -> str | None:
    """Why *unit* does not fit a value of *variable*, or None (also when it cannot be told
    without Pint)."""
    from chemeascode.foundation.units import (
        PRESSURE_UNITS,
        TEMPERATURE_UNITS,
        UnitError,
        convert_units,
    )

    if variable == "pressure":
        if unit in PRESSURE_UNITS:
            return None
        return f"pressure unit {unit!r}: write it with (a) or (g), e.g. bar(g), kPa(a)"
    if variable == "temperature":
        return None if unit in TEMPERATURE_UNITS else f"temperature unit {unit!r}: use K or °C"
    references = _REFERENCE.get(variable or "")
    if references is None or unit == "%" or variable == "flow" and _STANDARD_VOLUME.match(unit):
        return None
    for reference in references:
        try:
            convert_units(1.0, unit, reference)
            return None
        except UnitError as failure:
            if "needs Pint" in str(failure):
                return None
    return f"{unit!r} is not a unit of {variable}"


def _loop_findings(check: _Checker, source: _Source) -> None:
    seen: dict[str, int] = {}
    for position, loop in enumerate(check.raw_loops):
        loc: Loc = ("loops", position)
        if loop.id in seen:
            check.add(
                source,
                "error",
                "cheme.control-duplicate",
                f"loop {loop.id} is given twice (first at entry {seen[loop.id] + 1})",
                (*loc, "id"),
                [loop.id],
                "give each loop its own id",
            )
            continue
        seen[loop.id] = position
        _loop(check, source, loop, loc)
    _cycles(check, source)
    _shared_elements(check, source)


def _loop(check: _Checker, source: _Source, loop: Any, loc: Loc) -> None:
    owner = f"loop {loop.id}"
    if loop.section is not None:
        check.ref(source, owner, "section", loop.section, (*loc, "section"))
    for i, case in enumerate(loop.cases):
        check.ref(source, owner, "case", case, (*loc, "cases", i))
    if loop.variable is None:
        check.incomplete(
            source, owner, "what it controls (variable) is not stated", loc, "give variable"
        )
    if not loop.measurement:
        check.incomplete(
            source,
            owner,
            "no measurement",
            loc,
            "name the measuring instrument, or record in unresolved what is missing",
        )
    for i, measurement in enumerate(loop.measurement):
        check.tag(source, owner, measurement.tag, (*loc, "measurement", i, "tag"))
    if loop.controller is not None:
        check.tag(source, owner, loop.controller, (*loc, "controller"))
    if loop.action is None:
        check.incomplete(
            source,
            owner,
            "the controller action (direct or reverse) is not stated",
            loc,
            "direct: the output rises as the measurement rises; independent of the valve",
        )
    masters = {
        link.loop
        for other in check.loops.values()
        for link in other.links
        if link.type == "cascade"
    }
    if not loop.final_elements and loop.id not in masters:  # a master moves its slave's setpoint
        check.incomplete(
            source,
            owner,
            "no final element (valve, drive, heater)",
            loc,
            "name what the output moves, or record in unresolved what is missing",
        )
    for i, element in enumerate(loop.final_elements):
        where = (*loc, "final_elements", i)
        check.tag(source, owner, element.tag, (*where, "tag"))
        if element.fail is None:
            check.incomplete(
                source,
                owner,
                f"the fail position of {element.tag} is not stated",
                where,
                "give fail: open, closed, last (a drive stop, a heater off)",
            )
    ranged = [e for e in loop.final_elements if e.range is not None]
    if len(loop.final_elements) > 1 and len(ranged) != len(loop.final_elements):
        check.add(
            source,
            "warning",
            "cheme.control-conflict",
            f"{owner}: {len(loop.final_elements)} final elements, but not each with the range "
            "of the output it acts on",
            (*loc, "final_elements"),
            [owner],
            "give each element its range (split range), or move one to its own loop",
        )
    elif len(loop.final_elements) == 1 and ranged:
        check.add(
            source,
            "warning",
            "cheme.control-conflict",
            f"{owner}: a split range with a single final element",
            (*loc, "final_elements", 0, "range"),
            [owner],
            "drop range, or add the other elements of the split range",
        )
    if not loop.targets:
        check.incomplete(
            source,
            owner,
            "no setpoint or operating target",
            loc,
            "give the setpoint (and limits) with units and provenance, or a target with unresolved",
        )
    for i, target in enumerate(loop.targets):
        check.target(source, owner, target, (*loc, "targets", i), loop.variable, loop.cases)
    _target_conflicts(check, source, owner, loop, loc)
    _modes(check, source, owner, loop, loc)
    for i, link in enumerate(loop.links):
        _link(check, source, owner, loop, link, (*loc, "links", i))
    for i, alarm in enumerate(loop.alarms):
        where = (*loc, "alarms", i)
        check.tag(source, owner, alarm.tag, (*where, "tag"))
        if alarm.limit is not None:
            check.target(
                source,
                owner,
                alarm.limit,
                (*where, "limit"),
                loop.variable,
                loop.cases,
                label=f"limit of alarm {alarm.tag} {alarm.condition}",
            )
        if not alarm.response.strip():
            check.incomplete(
                source,
                owner,
                f"alarm {alarm.tag} {alarm.condition} has no operator response",
                where,
                "say what the operator does on it (response)",
            )
        if _TRIP.search(alarm.condition.strip()):
            check.add(
                source,
                "info",
                "cheme.control-alarm-trip",
                f"{owner}: alarm {alarm.tag} {alarm.condition} is at a trip level",
                (*where, "condition"),
                [owner, alarm.tag],
                "a trip belongs in control/cause-effect.yaml; list the interlock in interlocks",
            )
    for i, interlock in enumerate(loop.interlocks):
        check.ref(source, owner, "interlock", interlock, (*loc, "interlocks", i))
    check.unresolved(source, owner, loop.unresolved, (*loc, "unresolved"))


def _overlap(a: list[str], b: list[str]) -> bool:
    return not a or not b or bool(set(a) & set(b))


def _target_conflicts(check: _Checker, source: _Source, owner: str, loop: Any, loc: Loc) -> None:
    values = [(i, t) for i, t in enumerate(loop.targets) if t.value is not None and t.unit]
    for i, setpoint in values:
        if setpoint.kind != "setpoint":
            continue
        for _, limit in values:
            if limit.kind == "setpoint" or limit.unit != setpoint.unit:
                continue
            if not (
                _overlap(limit.modes, setpoint.modes) and _overlap(limit.cases, setpoint.cases)
            ):
                continue
            outside = (limit.kind == "low" and setpoint.value < limit.value) or (
                limit.kind == "high" and setpoint.value > limit.value
            )
            if outside:
                check.add(
                    source,
                    "warning",
                    "cheme.control-conflict",
                    f"{owner}: the setpoint {setpoint.value:g} {setpoint.unit} is outside its "
                    f"{limit.kind} limit {limit.value:g} {limit.unit}",
                    (*loc, "targets", i, "value"),
                    [owner],
                    "correct the setpoint or the limit",
                    key=f"{'.'.join(map(str, loc))}.targets.{i}:{limit.kind}",
                )


def _modes(check: _Checker, source: _Source, owner: str, loop: Any, loc: Loc) -> None:
    if not loop.modes:
        check.incomplete(
            source,
            owner,
            "its modes (manual, auto, cascade) are not stated",
            loc,
            "give modes and normal_mode",
        )
        return
    modes = set(loop.modes)
    if loop.normal_mode is not None and loop.normal_mode not in modes:
        check.add(
            source,
            "warning",
            "cheme.control-conflict",
            f"{owner}: normal_mode {loop.normal_mode} is not one of its modes",
            (*loc, "normal_mode"),
            [owner],
            "add the mode to modes, or correct normal_mode",
        )
    for i, transition in enumerate(loop.transitions):
        where = (*loc, "transitions", i)
        for end in dict.fromkeys((transition.from_, transition.to)):
            if end not in modes:
                check.add(
                    source,
                    "warning",
                    "cheme.control-conflict",
                    f"{owner}: the transition {transition.from_} -> {transition.to} names "
                    f"mode {end}, which it does not have",
                    where,
                    [owner],
                    "add the mode to modes, or correct the transition",
                    key=f"{'.'.join(map(str, where))}:{end}",
                )
        if transition.condition is not None:
            check.condition(source, owner, transition.condition, (*where, "condition"))
    cascaded = any(link.type == "cascade" for link in loop.links)
    if cascaded and "cascade" not in modes:
        check.add(
            source,
            "warning",
            "cheme.control-conflict",
            f"{owner}: its setpoint comes from a master loop (cascade), but cascade is not one "
            "of its modes",
            (*loc, "modes"),
            [owner],
            "add cascade to modes",
        )


def _link(check: _Checker, source: _Source, owner: str, loop: Any, link: Any, loc: Loc) -> None:
    if link.loop == loop.id:
        check.add(
            source,
            "error",
            "cheme.control-cycle",
            f"{owner}: a {link.type} link to itself",
            (*loc, "loop"),
            [owner],
            "name the other loop",
        )
        return
    if link.loop is not None:
        check.ref(source, owner, "loop", link.loop, (*loc, "loop"))
    if link.tag is not None:
        check.tag(source, owner, link.tag, (*loc, "tag"))
    if link.type == "override":
        if link.select is None:
            check.incomplete(
                source, owner, f"override with {link.loop}: no selector", loc, "give select"
            )
        other = check.loops.get(link.loop or "")
        if other is not None:
            mine = {e.tag for e in loop.final_elements}
            if mine and other.final_elements and not mine & {e.tag for e in other.final_elements}:
                check.add(
                    source,
                    "warning",
                    "cheme.control-conflict",
                    f"{owner}: override with {other.id}, but the two share no final element",
                    loc,
                    [owner, other.id],
                    "an override selects between loops that drive the same element",
                )
    if link.type == "ratio" and link.ratio is None:
        check.incomplete(source, owner, "the ratio is not given", loc, "give ratio")


def _cycles(check: _Checker, source: _Source) -> None:
    """Cascade and ratio links in a ring: no setpoint could be computed."""
    edges = {
        loop.id: sorted(
            {
                link.loop
                for link in loop.links
                if link.type == "cascade" and link.loop in check.loops and link.loop != loop.id
            }
        )
        for loop in check.loops.values()
    }
    reported: set[frozenset[str]] = set()
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in edges.get(node, []):
            if state.get(nxt) == 1:
                ring = stack[stack.index(nxt) :]
                if frozenset(ring) not in reported:
                    reported.add(frozenset(ring))
                    position = [loop.id for loop in check.raw_loops].index(ring[0])
                    check.add(
                        source,
                        "error",
                        "cheme.control-cycle",
                        "the setpoints of loops " + " -> ".join([*ring, ring[0]]) + " depend "
                        "on each other (cascade links in a ring)",
                        ("loops", position, "links"),
                        sorted(ring),
                        "a master sets its slave's setpoint, never the other way round; break "
                        "the ring",
                        key="+".join(sorted(ring)),
                    )
            elif state.get(nxt) is None:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for node in edges:
        if node not in state:
            visit(node)


def _shared_elements(check: _Checker, source: _Source) -> None:
    """Two loops on one final element without an override between them; a loop that measures
    or moves a tag of an interlock."""
    positions = {loop.id: i for i, loop in reversed(list(enumerate(check.raw_loops)))}
    drivers: dict[str, list[str]] = {}
    for loop in check.loops.values():
        for element in loop.final_elements:
            drivers.setdefault(element.tag, []).append(loop.id)
    for tag, ids in drivers.items():
        pairs = [(a, b) for n, b in enumerate(ids) for a in ids[:n]]
        for first, later in pairs:
            linked = any(
                link.type == "override" and link.loop in (first, later)
                for loop_id in (first, later)
                for link in check.loops[loop_id].links
            )
            if linked:
                continue
            check.add(
                source,
                "warning",
                "cheme.control-conflict",
                f"loops {first} and {later} both drive {tag}, with no override between them",
                ("loops", positions[later], "final_elements"),
                [first, later, tag],
                "link them with an override (select low or high), or give the element to one loop",
                key=f"{tag}:{first}+{later}",
            )
    controllers: dict[str, str] = {}
    for loop in check.loops.values():
        if loop.controller is None:
            continue
        if loop.controller in controllers:
            check.add(
                source,
                "warning",
                "cheme.control-conflict",
                f"loops {controllers[loop.controller]} and {loop.id} name the same controller "
                f"{loop.controller}",
                ("loops", positions[loop.id], "controller"),
                [controllers[loop.controller], loop.id],
                "one controller is one loop; correct the controller tag",
            )
        else:
            controllers[loop.controller] = loop.id
    for interlock in (check.interlocks or {}).values():
        tags = {interlock.cause.tag} | {e.tag for e in interlock.effects}
        for item, _ in walk(interlock.logic):
            if item.tag:
                tags.add(item.tag)
        for loop in check.loops.values():
            shared = sorted(
                ({m.tag for m in loop.measurement} | {e.tag for e in loop.final_elements}) & tags
            )
            if shared:
                check.add(
                    source,
                    "info",
                    "cheme.control-shared-element",
                    f"loop {loop.id} shares {', '.join(shared)} with interlock {interlock.id}: "
                    "the loop is not independent of the interlock",
                    ("loops", positions[loop.id]),
                    [loop.id, interlock.id, *shared],
                    "nothing to fix when meant; the HAZOP and SIL study judge independence",
                    key=f"{loop.id}:{interlock.id}",
                )


def _sequence_findings(check: _Checker, source: _Source) -> None:
    seen: dict[str, int] = {}
    for position, sequence in enumerate(check.raw_sequences):
        loc: Loc = ("sequences", position)
        if sequence.id in seen:
            check.add(
                source,
                "error",
                "cheme.control-duplicate",
                f"sequence {sequence.id} is given twice (first at entry {seen[sequence.id] + 1})",
                (*loc, "id"),
                [sequence.id],
                "give each sequence its own id",
            )
            continue
        seen[sequence.id] = position
        _sequence(check, source, sequence, loc)


def _actions(check: _Checker, source: _Source, owner: str, actions: list[Any], loc: Loc) -> None:
    for i, action in enumerate(actions):
        where = (*loc, i)
        if action.tag is not None:
            check.tag(source, owner, action.tag, (*where, "tag"))
        if action.sequence is not None:
            check.ref(source, owner, "sequence", action.sequence, (*where, "sequence"))
        if action.loop is not None:
            check.ref(source, owner, "loop", action.loop, (*where, "loop"))
            loop = check.loops.get(action.loop)
            mode = action.action in ("manual", "auto", "cascade")
            if loop is not None and loop.modes and mode and action.action not in loop.modes:
                check.add(
                    source,
                    "warning",
                    "cheme.control-conflict",
                    f"{owner}: puts loop {loop.id} in {action.action}, which is not one of "
                    "its modes",
                    (*where, "action"),
                    [owner, loop.id],
                    "correct the action, or add the mode to the loop",
                )
            if action.setpoint is not None:
                check.target(
                    source,
                    owner,
                    action.setpoint,
                    (*where, "setpoint"),
                    loop.variable if loop is not None else None,
                    loop.cases if loop is not None else [],
                )
        if action.text is not None:
            check.add(
                source,
                "info",
                "cheme.control-logic-text",
                f"{owner}: action given as text is not checked: {action.text}",
                (*where, "text"),
                [owner],
                "write it as a tag, loop or sequence action where the format can express it",
            )


def _sequence(check: _Checker, source: _Source, sequence: Any, loc: Loc) -> None:
    owner = f"sequence {sequence.id}"
    if sequence.section is not None:
        check.ref(source, owner, "section", sequence.section, (*loc, "section"))
    for i, case in enumerate(sequence.cases):
        check.ref(source, owner, "case", case, (*loc, "cases", i))
    for i, tag in enumerate(sequence.equipment):
        check.tag(source, owner, tag, (*loc, "equipment", i))
    for i, interlock in enumerate(sequence.interlocks):
        check.ref(source, owner, "interlock", interlock, (*loc, "interlocks", i))
    steps = [step.id for step in sequence.steps]
    known = set(steps)
    for i, permissive in enumerate(sequence.permissives):
        check.condition(source, owner, permissive, (*loc, "permissives", i), known)
    if sequence.mode == "startup" and not sequence.permissives:
        check.incomplete(
            source,
            owner,
            "a startup sequence without start permissives",
            loc,
            "list what must hold before it may start (permissives)",
        )
    if not sequence.steps:
        check.incomplete(source, owner, "no steps", loc, "give its steps")
    seen: set[str] = set()
    for i, step in enumerate(sequence.steps):
        where = (*loc, "steps", i)
        name = f"{owner} step {step.id}"
        if step.id in seen:
            check.add(
                source,
                "error",
                "cheme.control-duplicate",
                f"{owner}: step {step.id} is given twice",
                (*where, "id"),
                [sequence.id, step.id],
                "give each step its own id",
            )
            continue
        seen.add(step.id)
        if step.entry is not None:
            check.condition(source, name, step.entry, (*where, "entry"), known)
        if step.complete is not None:
            check.condition(source, name, step.complete, (*where, "complete"), known)
        else:
            check.incomplete(
                source,
                name,
                "no completion condition",
                where,
                "give complete: what must hold before the next step",
            )
        if not step.actions and not step.operator.strip():
            check.incomplete(
                source, name, "no actions and no operator instruction", where, "give actions"
            )
        _actions(check, source, name, step.actions, (*where, "actions"))
        if step.timeout is not None:
            check.time(source, name, step.timeout, (*where, "timeout"))
            if step.on_timeout is None:
                check.incomplete(
                    source,
                    name,
                    "a timeout without what happens then",
                    (*where, "timeout"),
                    "give on_timeout: a step id or abort",
                )
        elif step.on_timeout is not None:
            check.add(
                source,
                "warning",
                "cheme.control-conflict",
                f"{name}: on_timeout without a timeout",
                (*where, "on_timeout"),
                [sequence.id, step.id],
                "give the timeout, or drop on_timeout",
            )
        for key, special in (("next", "end"), ("on_timeout", "abort")):
            value = getattr(step, key)
            if value is not None and value != special and value not in known:
                check.add(
                    source,
                    "warning",
                    "cheme.control-ref",
                    f"{name}: {key} {value} is not a step of the sequence",
                    (*where, key),
                    [sequence.id, value],
                    f"name a step of the sequence, or {special}",
                )
    _reachable(check, source, owner, sequence, loc)
    if sequence.abort is None:
        if sequence.mode != "normal":
            check.incomplete(
                source,
                owner,
                "what happens on abort is not stated",
                loc,
                "give abort: its condition, actions and the sequence that follows",
            )
    else:
        abort = sequence.abort
        if abort.condition is not None:
            check.condition(source, owner, abort.condition, (*loc, "abort", "condition"), known)
        _actions(check, source, owner, abort.actions, (*loc, "abort", "actions"))
        if abort.then is not None:
            check.ref(source, owner, "sequence", abort.then, (*loc, "abort", "then"))
    if sequence.reset is None:
        if sequence.interlocks or sequence.abort is not None:
            check.incomplete(
                source,
                owner,
                "reset and restart after an abort or trip are not stated",
                loc,
                "give reset: latching, manual, condition and restart",
            )
    else:
        reset = sequence.reset
        for key in ("condition", "restart"):
            value = getattr(reset, key)
            if value is not None:
                check.condition(source, owner, value, (*loc, "reset", key), known)
        if reset.latching is None:
            check.incomplete(
                source,
                owner,
                "whether the abort latches is not stated",
                (*loc, "reset"),
                "give reset.latching",
            )
    check.unresolved(source, owner, sequence.unresolved, (*loc, "unresolved"))


def _reachable(check: _Checker, source: _Source, owner: str, sequence: Any, loc: Loc) -> None:
    steps = sequence.steps
    if not steps:
        return
    index: dict[str, int] = {}
    for i, step in enumerate(steps):
        index.setdefault(step.id, i)
    reached = set()
    todo = [0]
    while todo:
        i = todo.pop()
        if i in reached:
            continue
        reached.add(i)
        step = steps[i]
        if step.next is None:
            if i + 1 < len(steps):
                todo.append(i + 1)
        elif step.next in index:
            todo.append(index[step.next])
        if step.on_timeout in index:
            todo.append(index[step.on_timeout])
    for i, step in enumerate(steps):
        if i not in reached and index.get(step.id) == i:
            check.add(
                source,
                "warning",
                "cheme.control-unreachable",
                f"{owner}: no step leads to step {step.id}",
                (*loc, "steps", i),
                [sequence.id, step.id],
                "correct next / on_timeout of the steps before it, or remove the step",
            )


def _document_findings(check: _Checker, document: Document) -> None:
    source = _Source(document.name, document.node, offset=1)
    check.findings += document.errors
    front = document.front
    if front is None:
        return
    if document.kind == "narrative":
        if not front.sections:
            check.findings.append(
                Finding(
                    document.name,
                    "info",
                    "cheme.control-incomplete",
                    "the narrative names no process sections in its front matter",
                    line=1,
                    hint="list the sections (id, title, equipment, loops, ...) in the front "
                    "matter, each with a heading ## <id> <title>",
                )
            )
        seen: set[str] = set()
        for i, section in enumerate(front.sections):
            loc: Loc = ("sections", i)
            owner = f"section {section.id}"
            if section.id in seen:
                check.add(
                    source,
                    "error",
                    "cheme.control-duplicate",
                    f"section {section.id} is given twice",
                    (*loc, "id"),
                    [section.id],
                    "give each section its own id",
                )
                continue
            seen.add(section.id)
            _refs(check, source, owner, section, loc)
            for j, block in enumerate(section.blocks):
                check.ref(source, owner, "block", block, (*loc, "blocks", j))
            heading = re.compile(rf"{re.escape(section.id)}(?![\w-])")
            if not any(heading.match(h) for h in document.headings):
                check.incomplete(
                    source,
                    owner,
                    "has no heading in the text",
                    loc,
                    f"write its narrative under a heading ## {section.id} {section.title}".strip(),
                )
    else:
        for heading in PHILOSOPHY_HEADINGS:
            if not document.has_heading(heading):
                check.findings.append(
                    Finding(
                        document.name,
                        "info",
                        "cheme.control-incomplete",
                        f"the control philosophy has no section {heading!r}",
                        line=1,
                        hint=f"add a heading ## {heading} (the template has each)",
                        key=heading,
                    )
                )
        for kind in ("objectives", "failures"):
            ids: set[str] = set()
            for i, entry in enumerate(getattr(front, kind)):
                owner = f"{kind[:-1]} {entry.id}"
                if entry.id in ids:
                    check.add(
                        source,
                        "error",
                        "cheme.control-duplicate",
                        f"{owner} is given twice",
                        (kind, i, "id"),
                        [entry.id],
                        f"give each {kind[:-1]} its own id",
                    )
                    continue
                ids.add(entry.id)
                _refs(check, source, owner, entry, (kind, i))
    check.unresolved(source, document.name, front.unresolved, ("unresolved",))
    check.basis(source, document.name, front.basis)


def _refs(check: _Checker, source: _Source, owner: str, entry: Any, loc: Loc) -> None:
    for key, kind in (
        ("loops", "loop"),
        ("sequences", "sequence"),
        ("interlocks", "interlock"),
        ("cases", "case"),
    ):
        for i, value in enumerate(getattr(entry, key, []) or []):
            check.ref(source, owner, kind, value, (*loc, key, i))
    for i, tag in enumerate(getattr(entry, "equipment", []) or []):
        check.tag(source, owner, tag, (*loc, "equipment", i))


def has_records(
    workspace: Workspace, parsed: dict[str, Any], documents: dict[str, Document]
) -> bool:
    """Whether the plant documents its control: a document changed from its template, a loop
    or a sequence, or a loops or sequences file that does not load. The files ``cheme init``
    writes, unchanged, do not count."""
    for kind in ("loops", "sequences"):
        if workspace.list_file(kind) is not None and kind not in parsed:
            return True
        if getattr(parsed.get(kind), kind, None):
            return True
    return any(d.started for d in documents.values())


def control_findings(
    workspace: Workspace,
    sheets: dict[str, Any],
    parsed: dict[str, Any],
    partial: bool = False,
    documents: dict[str, Document] | None = None,
) -> list[Finding]:
    """The ``cheme.control-*`` findings of the loops, sequences, narrative and philosophy."""
    documents = load_documents(workspace) if documents is None else documents
    documents = {kind: d for kind, d in documents.items() if d.started}
    check = _Checker(workspace, sheets, parsed, partial, documents)
    for kind, run in (("loops", _loop_findings), ("sequences", _sequence_findings)):
        model = parsed.get(kind)
        if model is None:
            continue
        name = LIST_FILES[kind]
        source = _Source(name, _compose(workspace.root / name))
        run(check, source)
        check.basis(source, name, model.basis)
    for document in documents.values():
        _document_findings(check, document)
    return check.findings


def interlock_time_findings(workspace: Workspace, parsed: dict[str, Any]) -> list[Finding]:
    """``cheme.control-unit`` for a delay of a C&E interlock (its own or in its ``logic``)
    that is not a time; checked whether or not the plant has other control records."""
    model = parsed.get("interlocks")
    if model is None:
        return []
    name = LIST_FILES["interlocks"]
    node = _compose(workspace.root / name)
    found = []
    for position, interlock in enumerate(model.interlocks):
        loc: Loc = ("interlocks", position)
        owner = f"interlock {interlock.id}"
        delays = [((*loc, "delay"), interlock.delay)]
        delays += [
            ((*where, "delay"), item.delay)
            for item, where in walk(interlock.logic, (*loc, "logic"))
        ]
        for where, delay in delays:
            if delay is not None and not_a_time(delay.unit):
                level, rule, message = _time_finding(owner, delay.unit)
                found.append(
                    Finding(
                        name,
                        level,
                        rule,
                        message,
                        line=_yaml_line(node, (*where, "unit")),
                        ids=[owner],
                        hint=_TIME_HINT,
                        key=".".join(map(str, (*where, "unit"))),
                    )
                )
    return found
