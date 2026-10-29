"""Scenario propagation: candidate HAZOP scenarios of a node, walked over the P&IDs as drawn
(``cheme safety hazop propagate``).

For every object of the node and every failure mode the project's library
(``safety/failure-modes.yaml``, :class:`~chemeascode.domains.safety.schemas.FailureModeLibrary`)
gives its class, the deviation the failure produces is followed along the piping, object by
object, with the library's response of each object it reaches: it turns into another deviation,
passes, is absorbed, or stops the chain at a top event. A walk that brings a deviation to an
object of the node is a candidate scenario of that deviation: a *local* cause when it starts at
that object, a *driver* when it starts at another object of the node.

The walk is deterministic and reads the pyDEXPI objects directly (no graph library): pipes give
the flow direction (source to target), a nozzle stands for its equipment, an off-page connector
is a study limit. Along the way it collects candidate safeguards that the plant has (an
instrument measuring the deviated parameter on the path, its controller, the C&E interlocks it
starts, a check valve against reverse flow, a relief device at a pressure deviation) without
ever stopping the chain for them. What the files do not settle (a fail position not recorded, a
response the library lacks, the fluid at a top event) is a question, never a choice.

Everything it returns is a proposal for the team: it decides nothing about credibility, outcome
or whether a safeguard works.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from chemeascode.domains.safety.schemas import (
    ClassEntry,
    FailureMode,
    FailureModeLibrary,
    PlantRef,
    Response,
)

#: Steps a walk takes at most before it ends (``depth``).
MAX_STEPS = 40
#: The measured variable of an instrument function by its first letter (ISA 5.1 convention).
MEASURED = {"F": "flow", "L": "level", "P": "pressure", "T": "temperature"}

End = Literal[
    "top-event", "study-limit", "absorbed", "visited", "no-connection", "unknown", "depth"
]


@dataclass(frozen=True)
class Deviation:
    parameter: str
    guide_word: str

    def text(self) -> str:
        return f"{self.guide_word} {self.parameter}"


@dataclass(frozen=True)
class Step:
    """An object the deviation reached, and what the object did with it."""

    sheet: str
    object: str
    tag: str | None
    cls: str
    deviation: Deviation
    #: ``cause``, or the library's response: responds, passes, no-effect, absorbs, stops.
    effect: str
    #: The object's key in the walk and the segment the deviation arrived by.
    key: int = field(compare=False, repr=False)
    segment: int | None = field(default=None, compare=False, repr=False)

    @property
    def label(self) -> str:
        return self.tag or self.object


@dataclass(frozen=True)
class CandidateSafeguard:
    kind: str  # instrument, control, interlock, check-valve, relief
    ref: str  # a tag, or an interlock id
    detail: str


@dataclass
class Candidate:
    """One walk that brings *deviation* to an object of the node: a candidate scenario."""

    deviation: Deviation
    #: The node object it reached with that deviation.
    at: str
    cause: str
    mode: str
    mechanism: str
    kind: Literal["local", "driver"]
    path: list[Step]
    #: Index in *path* of the step at the node object.
    reached: int
    end: End
    top_event: str | None
    fluid: str | None
    safeguards: list[CandidateSafeguard]
    questions: list[str]

    def path_text(self) -> str:
        return " > ".join(f"{s.label} ({s.deviation.text()}, {s.effect})" for s in self.path)


@dataclass
class Context:
    """Plant data the walk needs besides the P&IDs, read by the caller."""

    #: Instrument tag -> ids of the C&E interlocks it starts.
    interlocks: dict[str, list[str]] = field(default_factory=dict)
    #: Final element tag -> its fail position (control/loops.yaml).
    fail: dict[str, str] = field(default_factory=dict)


@dataclass
class Propagation:
    candidates: list[Candidate]
    #: Node members whose class has no entry in the library (no cause or response known).
    uncovered: list[str]
    #: Node members not found on the analysed sheets.
    unresolved: list[str]


# ---------------------------------------------------------------------------
# The index over the pyDEXPI objects
# ---------------------------------------------------------------------------


@dataclass
class _Object:
    sheet: str
    id: str
    tag: str | None
    cls: str
    classes: tuple[str, ...]
    fluid: str | None = None
    actuated: bool = False
    limit: bool = False

    @property
    def label(self) -> str:
        return self.tag or self.id


@dataclass
class _Instrument:
    tag: str
    measures: str | None
    #: Keys of the objects or segments it senses at.
    senses: list[int]
    #: Keys of the valves it actuates.
    finals: list[int]


@dataclass
class _Index:
    objects: dict[int, _Object] = field(default_factory=dict)
    #: Key -> (next key, segment key) along the flow, and against it.
    down: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    up: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    #: Segment key -> (sheet, line number, fluid).
    segments: dict[int, tuple[str, str | None, str | None]] = field(default_factory=dict)
    instruments: dict[int, _Instrument] = field(default_factory=dict)
    #: Instrument function key -> its object (its tag and class; never a walk node).
    functions: dict[int, _Object] = field(default_factory=dict)

    def sensing(self, key: int | None) -> list[_Instrument]:
        return [i for i in self.instruments.values() if key is not None and key in i.senses]


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _index(models: Iterable[tuple[str, Any]]) -> _Index:
    """The objects, pipes and instruments of the loaded *models* (``(sheet id, model)``)."""
    from pydexpi.pydexpi_classes.pydexpi_classes import TaggedPlantItem
    from pydexpi.toolkits.display_name import get_tag, instrument_tag
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    from chemeascode.domains.piping.sheet_query import dexpi_classes, piping_tag

    index = _Index()
    owner: dict[int, int] = {}  # nozzle -> its equipment

    def add(sheet: str, obj: Any, tag: str | None, fluid: str | None = None) -> None:
        classes = dexpi_classes(obj)
        index.objects.setdefault(
            id(obj),
            _Object(
                sheet,
                getattr(obj, "id", "") or "",
                tag,
                type(obj).__name__,
                classes,
                fluid,
                limit="PipeOffPageConnector" in classes,
            ),
        )

    def node(item: Any) -> int | None:
        key = owner.get(id(item), id(item))
        return key if key in index.objects else None

    for sheet, model in models:
        conceptual = model.conceptualModel
        for obj in get_all_instances_in_model(model):
            if isinstance(obj, TaggedPlantItem):
                add(sheet, obj, _text(get_tag(obj)))
                for nozzle in getattr(obj, "nozzles", None) or ():
                    owner[id(nozzle)] = id(obj)
        systems = getattr(conceptual, "pipingNetworkSystems", None) or ()
        for system in systems:
            line = _text(getattr(system, "lineNumber", None))
            for segment in system.segments or ():
                fluid = _text(getattr(segment, "fluidCode", None)) or _text(
                    getattr(system, "fluidCode", None)
                )
                index.segments[id(segment)] = (sheet, line, fluid)
                for item in segment.items or ():
                    add(sheet, item, _text(piping_tag(item)), fluid)
        # Pipes second: a pipe may end at an item of a segment listed after its own.
        for system in systems:
            for segment in system.segments or ():
                # A segment without pipes still joins its own ends.
                for pipe in segment.connections or [segment]:
                    source = node(getattr(pipe, "sourceItem", None))
                    target = node(getattr(pipe, "targetItem", None))
                    if source is None or target is None or source == target:
                        continue
                    index.down.setdefault(source, []).append((target, id(segment)))
                    index.up.setdefault(target, []).append((source, id(segment)))
        actuated_by: dict[int, int] = {}  # actuating system -> its valve
        for system in getattr(conceptual, "actuatingSystems", None) or ():
            reference = getattr(system, "operatedValveReference", None)
            valve = getattr(reference, "valve", None)
            if valve is not None and id(valve) in index.objects:
                index.objects[id(valve)].actuated = True
                actuated_by[id(system)] = id(valve)
        for function in getattr(conceptual, "processInstrumentationFunctions", None) or ():
            tag = _text(instrument_tag(function))
            if not tag:
                continue
            senses = []
            for generator in function.processSignalGeneratingFunctions or ():
                location = getattr(generator, "sensingLocation", None)
                if location is not None:
                    senses.append(node(location) or id(location))
            finals = []
            for actuating in getattr(function, "actuatingFunctions", None) or ():
                systems = getattr(actuating, "systems", None)
                for system in systems if isinstance(systems, list) else [systems]:
                    if system is not None and id(system) in actuated_by:
                        finals.append(actuated_by[id(system)])
            category = _text(getattr(function, "processInstrumentationFunctionCategory", None))
            index.instruments[id(function)] = _Instrument(
                tag, MEASURED.get((category or "")[:1].upper()), senses, finals
            )
            index.functions[id(function)] = _Object(
                sheet, function.id or "", tag, type(function).__name__, dexpi_classes(function)
            )
    return index


def _members(index: _Index, members: Iterable[PlantRef]) -> tuple[list[int], set[int], list[str]]:
    """The node's objects (equipment, piping items, instrument functions), the segments of its
    lines, and the members found on no analysed sheet."""
    keys: list[int] = []
    segments: set[int] = set()
    unresolved: list[str] = []
    every = {**index.objects, **index.functions}
    for ref in members:
        found = False
        for key, obj in every.items():
            if ref.sheet is not None and obj.sheet != ref.sheet:
                continue
            if (ref.tag is not None and obj.tag == str(ref.tag)) or (
                ref.object is not None and obj.id == ref.object
            ):
                found = True
                if key not in keys:
                    keys.append(key)
        if ref.tag is not None:
            for key, (sheet, line, _fluid) in index.segments.items():
                if line == str(ref.tag) and (ref.sheet is None or ref.sheet == sheet):
                    found = True
                    segments.add(key)
        if not found:
            unresolved.append(ref.text())
    return keys, segments, unresolved


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def _entry(library: FailureModeLibrary, classes: tuple[str, ...]) -> ClassEntry | None:
    """The library entry of the most specific class that has one."""
    return next((library.classes[c] for c in classes if c in library.classes), None)


def _applies(mode: FailureMode, obj: _Object, context: Context) -> tuple[bool, str | None]:
    """Whether *mode* can happen at *obj*, and the question it leaves."""
    if mode.needs == "actuation" and not obj.actuated:
        return False, None
    if mode.fail is None:
        return True, None
    known = context.fail.get(obj.tag or "")
    if known is None:
        return True, (
            f"fail position of {obj.label} not recorded (control/loops.yaml): this branch "
            f"assumes it fails {mode.fail}"
        )
    return known == mode.fail, None


def _matches(response: Response, deviation: Deviation, via: str) -> bool:
    incoming = response.incoming
    return (
        incoming.parameter == deviation.parameter
        and incoming.guide_word == deviation.guide_word
        and response.via in (via, "any")
    )


@dataclass
class _Walked:
    path: list[Step]
    end: End
    top_event: str | None
    questions: list[str]


class _Walker:
    def __init__(self, index: _Index, library: FailureModeLibrary) -> None:
        self.index = index
        self.library = library
        self.done: list[_Walked] = []

    def step(self, key: int, deviation: Deviation, effect: str, segment: int | None) -> Step:
        obj = self.index.objects[key]
        return Step(obj.sheet, obj.id, obj.tag, obj.cls, deviation, effect, key, segment)

    def advance(
        self, path: list[Step], deviation: Deviation, towards: str, questions: list[str]
    ) -> None:
        """Carry *deviation* on from the last object of *path*."""
        here = path[-1].key
        if towards == "none":
            self.react(path, here, path[-1].segment, deviation, "any", None, questions)
            return
        back = path[-2].key if len(path) > 1 else None
        directions = ("downstream", "upstream") if towards == "both" else (towards,)
        moved = False
        for direction in directions:
            edges = (self.index.down if direction == "downstream" else self.index.up).get(here, [])
            for following, segment in edges:
                if following == back:
                    continue  # never straight back to where it came from
                moved = True
                self.arrive(path, following, segment, deviation, direction, questions)
        if not moved:
            self.done.append(_Walked(path, "no-connection", None, questions))

    def arrive(
        self,
        path: list[Step],
        key: int,
        segment: int,
        deviation: Deviation,
        direction: str,
        questions: list[str],
    ) -> None:
        obj = self.index.objects[key]
        if len(path) >= MAX_STEPS:
            self.done.append(_Walked(path, "depth", None, questions))
            return
        if any(s.key == key and s.deviation == deviation for s in path):
            self.done.append(_Walked(path, "visited", None, questions))
            return
        if obj.limit:
            limit = self.step(key, deviation, "study-limit", segment)
            self.done.append(_Walked([*path, limit], "study-limit", None, questions))
            return
        via = "inlet" if direction == "downstream" else "outlet"
        self.react(path, key, segment, deviation, via, direction, questions)

    def react(
        self,
        path: list[Step],
        key: int,
        segment: int | None,
        deviation: Deviation,
        via: str,
        direction: str | None,
        questions: list[str],
    ) -> None:
        """Apply the library's responses of the object *key* to *deviation*."""
        obj = self.index.objects[key]
        entry = _entry(self.library, obj.classes)
        responses = [r for r in (entry.responses if entry else []) if _matches(r, deviation, via)]
        if not responses:
            unknown = self.step(key, deviation, "unknown", segment)
            where = f"arriving at its {via}" if via != "any" else "inside it"
            question = (
                f"the library gives no response of {obj.cls} ({obj.label}) to "
                f"{deviation.text()} {where}"
            )
            self.done.append(_Walked([*path, unknown], "unknown", None, [*questions, question]))
            return
        for response in responses:
            here = [*path, self.step(key, deviation, response.effect, segment)]
            if response.effect in ("passes", "no-effect"):
                if direction is None:  # a deviation that stays here has nowhere to pass to
                    self.done.append(_Walked(here, "no-connection", None, questions))
                else:
                    self.advance(here, deviation, direction, questions)
            elif response.effect == "responds" and response.gives is not None:
                gives = response.gives
                turned = Deviation(gives.parameter, gives.guide_word)
                if gives.towards != "none":
                    self.advance(here, turned, gives.towards, questions)
                elif any(s.key == key and s.deviation == turned for s in here):
                    self.done.append(_Walked(here, "visited", None, questions))
                else:
                    self.react(here, key, segment, turned, "any", None, questions)
            elif response.effect == "absorbs":
                self.done.append(_Walked(here, "absorbed", None, questions))
            else:
                self.done.append(_Walked(here, "top-event", response.top_event, questions))


def _safeguards(index: _Index, path: list[Step], context: Context) -> list[CandidateSafeguard]:
    found: list[CandidateSafeguard] = []

    def add(guard: CandidateSafeguard) -> None:
        if all(g.ref != guard.ref or g.kind != guard.kind for g in found):
            found.append(guard)

    for step in path:
        parameter = step.deviation.parameter
        line = index.segments.get(step.segment or 0, ("", None, None))[1]
        sensing = [(i, f"at {step.label}") for i in index.sensing(step.key)]
        sensing += [(i, f"on {line or 'the line'}") for i in index.sensing(step.segment)]
        for instrument, where in sensing:
            if instrument.measures != parameter:
                continue
            kind = "control" if instrument.finals else "instrument"
            add(CandidateSafeguard(kind, instrument.tag, f"measures {parameter} {where}"))
            for interlock in context.interlocks.get(instrument.tag, []):
                add(CandidateSafeguard("interlock", interlock, f"started by {instrument.tag}"))
        classes = index.objects[step.key].classes
        if "CheckValve" in classes and step.deviation.guide_word == "reverse":
            add(CandidateSafeguard("check-valve", step.label, "on the path of the reverse flow"))
        if parameter == "pressure":
            nearby = [step.key] + [k for k, _ in index.down.get(step.key, [])]
            for key in nearby:
                obj = index.objects[key]
                if "SafetyValveOrFitting" in obj.classes:
                    add(CandidateSafeguard("relief", obj.label, f"relieves at {step.label}"))
    return found


def _fluid(index: _Index, step: Step) -> str | None:
    if step.segment is not None and step.segment in index.segments:
        return index.segments[step.segment][2]
    return index.objects[step.key].fluid


def propagate(
    models: Iterable[tuple[str, Any]],
    library: FailureModeLibrary,
    members: Iterable[PlantRef],
    context: Context | None = None,
    deviation: Deviation | None = None,
) -> Propagation:
    """The candidate scenarios of a node with *members*, over the loaded *models* (``(sheet id,
    pyDEXPI model)``), for one *deviation* or every one a cause reaches the node with."""
    context = context or Context()
    index = _index(models)
    member_list = list(members)
    keys, segments, unresolved = _members(index, member_list)
    in_node = set(keys)

    uncovered = []
    for key in keys:
        obj = index.objects.get(key) or index.functions[key]
        if _entry(library, obj.classes) is None:
            uncovered.append(f"{obj.label} ({obj.cls})")

    candidates: list[Candidate] = []
    seen: set[tuple[Any, ...]] = set()
    for key in keys:
        obj = index.objects.get(key) or index.functions[key]
        entry = _entry(library, obj.classes)
        for mode in entry.modes if entry else []:
            if mode.at == "final-element":
                starts = index.instruments[key].finals if key in index.instruments else []
            else:
                starts = [key] if key in index.objects else []
            for start in starts:
                applies, question = _applies(mode, index.objects[start], context)
                if not applies:
                    continue
                walker = _Walker(index, library)
                first = Deviation(mode.gives.parameter, mode.gives.guide_word)
                cause = walker.step(start, first, "cause", None)
                walker.advance([cause], first, mode.gives.towards, [question] if question else [])
                for walked in walker.done:
                    reached_here: set[Deviation] = set()
                    for i, step in enumerate(walked.path):
                        if step.key not in in_node and step.segment not in segments:
                            continue
                        if deviation is not None and step.deviation != deviation:
                            continue
                        if step.deviation in reached_here:
                            continue
                        reached_here.add(step.deviation)
                        signature = (
                            step.deviation,
                            obj.label,
                            mode.id,
                            tuple(s.key for s in walked.path),
                            walked.end,
                        )
                        if signature in seen:
                            continue
                        seen.add(signature)
                        questions = list(walked.questions)
                        last = walked.path[-1]
                        fluid = _fluid(index, last)
                        if walked.end == "top-event" and fluid is None:
                            questions.append(f"the fluid at {last.label} is not known")
                        candidates.append(
                            Candidate(
                                deviation=step.deviation,
                                at=step.label,
                                cause=obj.label,
                                mode=mode.id,
                                mechanism=mode.mechanism,
                                kind="local" if i == 0 else "driver",
                                path=walked.path,
                                reached=i,
                                end=walked.end,
                                top_event=walked.top_event,
                                fluid=fluid,
                                safeguards=_safeguards(index, walked.path, context),
                                questions=questions,
                            )
                        )
    return Propagation(candidates, uncovered, unresolved)
