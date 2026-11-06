"""Completeness of a HAZOP node: the deviations its equipment calls for and the cause families it
has to consider, besides the equipment failures the walk follows (``cheme safety hazop
propagate --coverage``; ADR 0036).

- **Deviations.** Each member of a node belongs to the equipment families of a deviation matrix
  by its DEXPI class (a line member counts as ``PipingNetworkSegment``); each family names the
  guide words meaningful for each of its parameters. An expected deviation the node does not
  develop (no deviation of that guide word and parameter with a scenario or ``notes``) and the
  triage does not decide is a gap. The default matrix is general HAZOP practice written for
  cheme-as-code; ``safety/deviation-matrix.yaml`` replaces it.
- **Cause families.** One prompt per node and family that applies, listing the plant items that
  make it concrete: ``utility`` (the design basis utilities) and ``external`` (the design basis
  site entries that name a hazard, and fire), asked once per item at the study's node without
  members when it has one, else for every node with members; ``boundary`` (the off-page connectors
  in or next to the node), ``operator`` (manual valves, filters and strainers, blinds, hand
  switches) and ``control`` (controllers, and the C&E interlocks that name a member) where the
  node has them. A prompt whose items a scenario of the node names in its ``refs`` (tag or
  object id) is covered; otherwise the triage decides it.

Both checks only ask: they never judge a scenario's text, and they decide nothing about
credibility. A node without members (a global node) gets neither.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.safety.propagation import _controller, _Index, _members
from chemeascode.domains.safety.schemas import (
    DEVIATION_MATRIX_SCHEMA,
    CauseFamily,
    DeviationMatrix,
    Node,
    Outcome,
)

#: The deviations each equipment family calls for: general HAZOP practice, written for
#: cheme-as-code (no published table). A project's safety/deviation-matrix.yaml replaces it.
DEFAULT_MATRIX = DeviationMatrix.model_validate(
    {
        "schema": DEVIATION_MATRIX_SCHEMA,
        "kind": "hazop-deviation-matrix",
        "source": "cheme-as-code default: general HAZOP practice (ADR 0036)",
        "families": [
            {
                "id": "line",
                "title": "line and piping",
                "classes": ["PipingNetworkSegment", "PipingComponent"],
                "deviations": {
                    "flow": ["no", "less", "more", "reverse"],
                    "pressure": ["more", "less"],
                    "temperature": ["more", "less"],
                    "composition": ["as-well-as", "other-than"],
                },
            },
            {
                "id": "vessel",
                "title": "vessel, tank, column or separator",
                "classes": ["Vessel", "ProcessColumn", "Separator"],
                "deviations": {
                    "level": ["more", "less"],
                    "pressure": ["more", "less"],
                    "temperature": ["more", "less"],
                    "composition": ["as-well-as", "other-than"],
                },
            },
            {
                "id": "heat-exchanger",
                "title": "heat exchanger or heater",
                "classes": ["HeatExchanger", "Heater"],
                "deviations": {"temperature": ["more", "less"], "composition": ["as-well-as"]},
            },
            {
                "id": "machine",
                "title": "pump, compressor, blower or fan",
                "classes": ["Pump", "Compressor", "Blower", "Fan"],
                "deviations": {
                    "flow": ["no", "less", "more", "reverse"],
                    "pressure": ["more", "less"],
                },
            },
            {
                "id": "relief",
                "title": "relief device",
                "classes": ["SafetyValveOrFitting"],
                "deviations": {"flow": ["more", "no"]},
            },
            {
                "id": "filter",
                "title": "filter or strainer",
                "classes": ["Filter", "Strainer", "ConicalStrainer"],
                "deviations": {"pressure": ["more"], "composition": ["as-well-as"]},
            },
        ],
    }
)

#: Classes of items an operator moves or opens by hand besides a valve without an actuator.
MANUAL_CLASSES = ("Filter", "Strainer", "ConicalStrainer", "LineBlind")
#: The order the cause families are reported in.
FAMILIES: tuple[CauseFamily, ...] = ("utility", "external", "boundary", "operator", "control")
#: Families covered when a scenario names one of their items in ``refs``.
BY_REFS = ("boundary", "operator", "control")
#: Design basis ``site`` keys that name a hazard (fire is always asked); others (location,
#: occupancy) describe the site and ask nothing.
SITE_HAZARDS = (
    "climate", "ambient", "temperature", "weather", "seismic", "earthquake", "flood", "wind",
    "lightning", "snow", "ice", "storm", "rain", "sand", "dust", "corros", "tsunami", "hazard",
)  # fmt: skip
#: What each family asks.
ASKS = {
    "utility": "loss or degradation of a utility the node depends on",
    "external": "an external or site cause acting on the node",
    "boundary": "a deviation entering from beyond the study boundary",
    "operator": "an operator or maintenance action (wrong line-up, opened or closed in error, "
    "left open or blinded after maintenance)",
    "control": "a control or trip function acting wrongly (spurious, failing to act, wrong set "
    "point)",
}


@dataclass
class Plant:
    """The plant data the cause families list besides the P&IDs, read by the caller."""

    #: process/design-basis.yaml ``utilities`` and ``site``.
    utilities: list[dict[str, Any]] = field(default_factory=list)
    site: dict[str, Any] = field(default_factory=dict)
    #: C&E interlock id -> every tag it names (cause, logic, effects).
    interlocks: dict[str, set[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Item:
    """A plant item a prompt lists, and the names a scenario's ``refs`` may give it."""

    label: str
    names: tuple[str, ...] = ()
    detail: str = ""

    def text(self) -> str:
        return f"{self.label} ({self.detail})" if self.detail else self.label


@dataclass
class DeviationGap:
    """An expected deviation the node does not develop and the triage does not decide."""

    guide_word: str
    parameter: str
    #: The families of the node's members that call for it.
    families: list[str]

    def text(self) -> str:
        return f"{self.guide_word} {self.parameter}"


@dataclass
class CausePrompt:
    """A cause family the node has to consider, with the items that make it concrete."""

    family: CauseFamily
    items: list[Item]
    #: A study-wide prompt is about one item (a utility, a site hazard) and is decided alone.
    item: str | None = None

    @property
    def asks(self) -> str:
        return ASKS[self.family]


@dataclass
class Completeness:
    """One node's open deviation gaps and cause prompts, and how the others were closed."""

    deviations: list[DeviationGap]
    causes: list[CausePrompt]
    #: Expected deviations the study develops, and those the triage decides.
    developed: int = 0
    deviations_dismissed: int = 0
    deviations_questions: int = 0
    #: Cause prompts covered (by a scenario's refs or a covered decision), dismissed, questions.
    covered: int = 0
    causes_dismissed: int = 0
    causes_questions: int = 0


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def families(classes: set[str], matrix: DeviationMatrix = DEFAULT_MATRIX) -> list[str]:
    """The ids of the matrix's families any of *classes* (DEXPI class names of the node's
    members with their superclasses) belongs to, in matrix order."""
    return [f.id for f in matrix.families if classes & set(f.classes)]


def expected(
    classes: set[str], matrix: DeviationMatrix = DEFAULT_MATRIX
) -> dict[tuple[str, str], list[str]]:
    """(guide word, parameter) -> the families calling for it, for members of *classes*."""
    out: dict[tuple[str, str], list[str]] = {}
    for family in matrix.families:
        if not classes & set(family.classes):
            continue
        for parameter, guide_words in family.deviations.items():
            for guide_word in guide_words:
                out.setdefault((guide_word, _norm(parameter)), []).append(family.id)
    return out


def node_classes(index: _Index, node: Node) -> set[str]:
    """The DEXPI classes of the node's members (with superclasses); a line member adds
    ``PipingNetworkSegment``."""
    keys, segments, _ = _members(index, node.members)
    every = {**index.objects, **index.functions}
    classes = {c for key in keys for c in every[key].classes}
    if segments:
        classes.add("PipingNetworkSegment")
    return classes


def deviation_gaps(
    node: Node,
    classes: set[str],
    decided: Iterable[Outcome] = (),
    matrix: DeviationMatrix = DEFAULT_MATRIX,
) -> tuple[list[DeviationGap], int, int, int]:
    """The expected deviations of *node* (members of *classes*) it does not develop and no
    decided ``deviation`` outcome handles; with the counts developed, dismissed, questions."""
    developed = {
        (d.guide_word, _norm(d.parameter))
        for d in node.deviations
        if d.scenarios or d.notes.strip()
    }
    decisions = [
        o for o in decided if o.kind == "deviation" and o.node == node.id and o.status != "open"
    ]
    gaps: list[DeviationGap] = []
    counts = {"developed": 0, "dismissed": 0, "question": 0}
    for (guide_word, parameter), by in expected(classes, matrix).items():
        if (guide_word, parameter) in developed:
            counts["developed"] += 1
            continue
        decision = next(
            (
                o
                for o in decisions
                if _norm(o.parameter) == parameter and o.guide_word in (None, guide_word)
            ),
            None,
        )
        if decision is not None:
            counts[decision.status] += 1
        else:
            gaps.append(DeviationGap(guide_word, parameter, by))
    return gaps, counts["developed"], counts["dismissed"], counts["question"]


def _site_items(site: dict[str, Any]) -> list[Item]:
    hazards = [k for k in site if any(h in str(k).lower() for h in SITE_HAZARDS)]
    return [Item(str(k), (), _short(site[k])) for k in hazards] + [Item("fire")]


def _utility_items(plant: Plant) -> list[Item]:
    return [
        Item(str(u.get("id") or u.get("title") or "?"), (), _short(u.get("title") or ""))
        for u in plant.utilities
    ]


def _short(value: Any, width: int = 60) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def _names(obj: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n for n in (obj.tag, obj.id) if n))


def cause_prompts(
    index: _Index, node: Node, plant: Plant, study_wide: str | None = None
) -> list[CausePrompt]:
    """Every cause family that applies to *node*, with its items (before any coverage). With
    *study_wide* (the study's node without members), utilities and site hazards are asked there,
    one prompt per item, instead of once per node."""
    if study_wide is not None and node.id == study_wide:
        return [CausePrompt("utility", [i], i.label) for i in _utility_items(plant)] + [
            CausePrompt("external", [i], i.label) for i in _site_items(plant.site)
        ]
    if not node.members:
        return []
    keys, segments, _ = _members(index, node.members)
    items = [k for k in keys if k in index.objects]
    functions = [index.functions[k] for k in keys if k in index.functions]
    prompts = (
        []
        if study_wide is not None
        else [
            CausePrompt("utility", _utility_items(plant)),
            CausePrompt("external", _site_items(plant.site)),
        ]
    )
    # The study limits in the node, next to one of its objects, or on one of its lines.
    in_node = set(items)
    limits = [k for k in items if index.objects[k].limit]
    for edges in (index.down, index.up):
        for here, nexts in edges.items():
            for there, segment in nexts:
                if (here in in_node or segment in segments) and index.objects[there].limit:
                    limits.append(there)
    boundary = [
        Item(index.objects[k].label, _names(index.objects[k])) for k in dict.fromkeys(limits)
    ]
    if boundary:
        prompts.append(CausePrompt("boundary", boundary))
    manual = [
        index.objects[k]
        for k in items
        if (index.objects[k].valve and not index.objects[k].actuated)
        or any(c in MANUAL_CLASSES for c in index.objects[k].classes)
    ]
    # Hand switches (ISA 5.1: H as the first letter) are moved by an operator too.
    manual += [f for f in functions if f.tag and f.tag.upper().startswith("H")]
    if manual:
        prompts.append(CausePrompt("operator", [Item(o.label, _names(o)) for o in manual]))
    tags = {o.tag for o in [*(index.objects[k] for k in items), *functions] if o.tag}
    control = [
        Item(f.label, _names(f), "controller") for f in functions if f.tag and _controller(f.tag)
    ]
    # By its id only: a trip instrument in a row's refs is mostly the safeguard, not the cause.
    control += [
        Item(interlock, (interlock,), "C&E")
        for interlock, named in plant.interlocks.items()
        if named & tags
    ]
    if control:
        prompts.append(CausePrompt("control", control))
    return prompts


def cause_coverage(
    node: Node, prompts: list[CausePrompt], decided: Iterable[Outcome] = ()
) -> tuple[list[CausePrompt], int, int, int]:
    """The *prompts* of *node* no scenario's refs and no decided ``cause`` outcome close; with
    the counts covered, dismissed, questions."""
    refs = {str(r.tag or r.object) for _, _, s in _rows(node) for r in s.refs}
    decisions = {
        (o.family, o.item): o
        for o in decided
        if o.kind == "cause" and o.node == node.id and o.status != "open"
    }
    counts = {"covered": 0, "dismissed": 0, "question": 0}
    open_: list[CausePrompt] = []
    for prompt in prompts:
        decision = decisions.get((prompt.family, prompt.item))
        if decision is not None:
            counts[decision.status] += 1
        elif prompt.family in BY_REFS and any(n in refs for i in prompt.items for n in i.names):
            counts["covered"] += 1
        else:
            open_.append(prompt)
    return open_, counts["covered"], counts["dismissed"], counts["question"]


def _rows(node: Node) -> list[tuple[Node, Any, Any]]:
    return [(node, d, s) for d in node.deviations for s in d.scenarios]


def check_decisions(nodes: Iterable[Node], outcomes: Iterable[Outcome]) -> list[str]:
    """What is wrong with the ``covered`` decisions of *outcomes*: a scenario id that is no
    scenario of its node (or a node not in the study)."""
    nodes = list(nodes)
    scenarios = {n.id: {s.id for _, _, s in _rows(n)} for n in nodes}
    every = {s for ids in scenarios.values() for s in ids}
    global_ = {n.id for n in nodes if not n.members}  # its study-wide prompts: any node's rows
    problems = []
    for o in outcomes:
        if o.status != "covered":
            continue
        if o.node not in scenarios:
            problems.append(f"{o.node} {o.family}: no node {o.node} in the study")
            continue
        allowed = every if o.node in global_ else scenarios[o.node]
        unknown = [s for s in o.scenarios if s not in allowed]
        if unknown:
            problems.append(
                f"{o.node} {o.family}: covered by {', '.join(unknown)}, no scenario of {o.node}"
            )
    return problems


def completeness(
    index: _Index,
    node: Node,
    plant: Plant,
    triage: Iterable[Outcome] = (),
    matrix: DeviationMatrix = DEFAULT_MATRIX,
    study_wide: str | None = None,
) -> Completeness:
    """Both checks for one node over the loaded P&IDs' *index*, the triage's decisions applied.
    A node without members gets no deviation gaps, and cause prompts only as *study_wide*."""
    if not node.members and node.id != study_wide:
        return Completeness([], [])
    decided = [o for o in triage if o.node == node.id and o.status != "open"]
    gaps, developed, dismissed, questions = (
        deviation_gaps(node, node_classes(index, node), decided, matrix)
        if node.members
        else ([], 0, 0, 0)
    )
    prompts, covered, c_dismissed, c_questions = cause_coverage(
        node, cause_prompts(index, node, plant, study_wide), decided
    )
    return Completeness(
        gaps, prompts, developed, dismissed, questions, covered, c_dismissed, c_questions
    )


def wanted(node_id: str, result: Completeness, by: str) -> list[Outcome]:
    """The ``open`` outcomes of *result*'s gaps, for the triage file."""
    out = [
        Outcome.model_validate(
            {
                "kind": "deviation",
                "node": node_id,
                "guide_word": g.guide_word,
                "parameter": g.parameter,
                "by": by,
            }
        )
        for g in result.deviations
    ]
    out += [
        Outcome.model_validate(
            {
                "kind": "cause",
                "node": node_id,
                "family": p.family,
                "item": p.item,
                "causes": [i.label for i in p.items],
                "by": by,
            }
        )
        for p in result.causes
    ]
    return out
