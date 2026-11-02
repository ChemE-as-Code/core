"""Schemas of the safety files: the risk matrix (``cheme/risk-matrix/v1``), the HAZOP study
(``cheme/hazop-study/v1``, ``safety/hazop/<study-id>/study.yaml``), the failure-mode library
scenario propagation walks with (``cheme/failure-modes/v1``, ``safety/failure-modes.yaml``) and
the triage of the walk's outcomes (``cheme/hazop-coverage/v1``,
``safety/hazop/<study-id>/coverage.yaml``) and the frequency library ratings may take their
likelihood from (``cheme/frequencies/v1``, ``safety/frequencies.yaml``).

A study is one nested file in worksheet order: nodes, their deviations (guide word and
parameter) and the scenarios of each deviation (a cause leading to a consequence), with the
study's safeguards and actions as registers that scenarios refer to by id. Every entity the
team or a tool refers to has a stable id (:data:`ID_PATTERN`); list order is display order only.

Who decided what stays visible:

- **judgement** (nodes, scenarios, safeguards, ratings) is ``status: proposed`` until the team
  accepts it (``accepted``); the default is ``proposed``, so nothing an agent drafts reads as
  agreed;
- **ratings** are authored inputs: severity and likelihood codes of the study's matrix, per
  category, each with its basis. Initial (before safeguards) and residual (with them) are rated
  separately; neither is ever derived from the other or from the safeguards listed;
- **bands** are the one calculated value: ``cheme safety hazop rate`` looks them up in the
  matrix and writes ``band: {value, provenance: calculated, source, fingerprint}``;
- **review decisions** stay in the review records (``reviews/*.md``).
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, field_validator, model_validator

from chemeascode.foundation.schema_base import (
    ID_PATTERN,
    Identifier,
    Strict,
    _identifier,
    unsupported_schema,
)
from chemeascode.foundation.schemas.reviews import Basis

MATRIX_SCHEMA = "cheme/risk-matrix/v1"
STUDY_SCHEMA = "cheme/hazop-study/v1"
FAILURE_MODES_SCHEMA = "cheme/failure-modes/v1"
COVERAGE_SCHEMA = "cheme/hazop-coverage/v1"
FREQUENCIES_SCHEMA = "cheme/frequencies/v1"


def _stable_id(value: Any) -> Any:
    value = _identifier(value)
    if isinstance(value, str) and not ID_PATTERN.match(value):
        raise ValueError(
            f"{value!r} is no stable id: letters, digits, _ and -, starting with a letter"
        )
    return value


#: An id of the matrix or the study: letters, digits, ``_`` and ``-``, starting with a letter.
StableId = Annotated[str, BeforeValidator(_stable_id)]
#: A severity or likelihood code as the matrix writes it (``3``, ``C``, ``S4``); a number in
#: YAML means the same as its text.
Code = Identifier


# ---------------------------------------------------------------------------
# Risk matrix
# ---------------------------------------------------------------------------


class Band(Strict):
    """A risk band, and what it asks of the study."""

    id: StableId
    title: str = ""
    description: str = ""
    requires_action: bool = Field(
        default=False,
        description="A scenario in this band needs an action (validate: hazop-action-required).",
    )


class Likelihood(Strict):
    """A likelihood grade."""

    code: Code
    title: str = ""
    description: str = Field(default="", description="What the grade means, e.g. a frequency.")
    max_frequency: float | None = Field(
        default=None,
        gt=0,
        description="Upper bound of the grade in events per year (a frequency below it and at or "
        "above the previous grade's bound is this grade; the most likely grade has none). Lets "
        "cheme safety hazop rate derive the code of a rating linked to a frequency record.",
    )


class Severity(Strict):
    """A severity grade, described per category."""

    code: Code
    title: str = ""
    descriptions: dict[str, str] = Field(
        default_factory=dict, description="By category id: what this grade means there."
    )


#: Severity code -> likelihood code -> band id.
Cells = dict[Code, dict[Code, str]]


class Category(Strict):
    """A category a consequence is rated in (people, environment, asset, reputation, ...)."""

    id: StableId
    title: str = ""
    cells: Cells | None = Field(
        default=None, description="This category's own cells; none: the matrix's cells."
    )


class RiskMatrix(Strict):
    """A risk matrix: explicit bands, grades and cells, each cell a band per category."""

    schema_: str = Field(alias="schema", description=f"Always {MATRIX_SCHEMA}.")
    kind: Literal["risk-matrix"]
    id: StableId
    title: str = ""
    example: bool = Field(
        default=False,
        description="True: illustrative data, not a company's risk criteria (validate says so "
        "for every study that uses it; gate hazop no-example fails).",
    )
    source: str = Field(default="", description="Where the criteria come from (a procedure).")
    status: Literal["proposed", "accepted"] = Field(
        default="proposed",
        description="proposed (the default) until the owner's team accepts the criteria for the "
        "studies (accepted); a study rated against a proposed matrix stays a draft.",
    )
    accepted_by: str = Field(default="", description="Who accepted it, and the procedure.")
    bands: list[Band] = Field(min_length=1, description="Lowest risk first: the band order.")
    likelihood: list[Likelihood] = Field(min_length=1, description="Least likely first.")
    severity: list[Severity] = Field(min_length=1, description="Least severe first.")
    categories: list[Category] = Field(min_length=1)
    cells: Cells | None = Field(
        default=None, description="Severity code -> likelihood code -> band id."
    )
    notes: str = ""

    @model_validator(mode="after")
    def _version(self) -> RiskMatrix:
        if self.schema_ != MATRIX_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, MATRIX_SCHEMA))
        bounds = [grade.max_frequency for grade in self.likelihood]
        if any(b is not None for b in bounds):
            given = bounds[:-1] if bounds[-1] is None else bounds
            if None in given or any(a >= b for a, b in zip(given, given[1:], strict=False)):
                raise ValueError(
                    "likelihood max_frequency: give every grade's bound, least likely first and "
                    "increasing (the most likely grade may have none)"
                )
        return self


# ---------------------------------------------------------------------------
# HAZOP study
# ---------------------------------------------------------------------------

#: Proposed (an agent's or one person's suggestion, the default) or accepted by the team.
Judgement = Literal["proposed", "accepted"]


def _guide_word(value: Any) -> Any:
    """``guide_word: no`` is read by YAML as false: it means the guide word ``no``."""
    return "no" if value is False else value


#: The guide words of IEC 61882 (YAML's ``no`` read as false is the guide word ``no``).
GuideWords = Literal[
    "no",
    "more",
    "less",
    "as-well-as",
    "part-of",
    "reverse",
    "other-than",
    "early",
    "late",
    "before",
    "after",
]
GuideWord = Annotated[GuideWords, BeforeValidator(_guide_word)]

#: What a safeguard is: basic process control, an alarm with operator response, an interlock
#: (a trip of control/cause-effect.yaml), a relief device, a check valve, a mechanical design
#: feature, a procedure, or something else.
SafeguardKind = Literal[
    "control",
    "alarm",
    "interlock",
    "relief",
    "check-valve",
    "mechanical",
    "procedural",
    "other",
]

#: ``proposed`` (suggested, not agreed), ``open`` (agreed, to be done), ``closed`` (done, with
#: its ``response``) or ``rejected`` (the team decided against it, with the reason).
ActionStatus = Literal["proposed", "open", "closed", "rejected"]

#: Data of other tools, by tool name; cheme-as-code keeps it and does not read it.
Extensions = dict[str, Any]

#: The events that end a chain: a loss of primary containment or a fire or explosion inside.
TopEvent = Literal["loss-of-containment", "overpressure", "overfill", "internal-fire-explosion"]


def _plant_ref(value: Any) -> Any:
    """``V-101`` is short for ``{tag: V-101}``."""
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        return {"tag": value}
    return value


class PlantRef(Strict):
    """A plant item: a printed tag (equipment, instrument, piping item or line number), on a
    given sheet where the tag alone is ambiguous, or a DEXPI object id on a sheet."""

    tag: Identifier | None = None
    sheet: str | None = Field(default=None, description="plant.yaml sheet id, e.g. P-01.")
    object: str | None = Field(default=None, description="DEXPI XML id on that sheet.")

    @model_validator(mode="after")
    def _named(self) -> PlantRef:
        if self.tag is None and self.object is None:
            raise ValueError("a plant reference needs a tag or an object (with its sheet)")
        if self.object is not None and self.sheet is None:
            raise ValueError("an object id needs its sheet")
        return self

    def text(self) -> str:
        name = self.tag or self.object or ""
        return f"{name} ({self.sheet})" if self.sheet else name


PlantRefs = list[Annotated[PlantRef, BeforeValidator(_plant_ref)]]


class BandInputs(Strict):
    """The inputs a band was looked up from, as the lookup saw them."""

    matrix: Identifier = Field(description="The matrix fingerprint.")
    category: str | None = Field(
        default=None,
        description="The category it was looked up in (written since 0.9.0; without it, the "
        "category is the one of the matrix's whose fingerprint matches).",
    )
    severity: Code
    likelihood: Code


class CalculatedBand(Strict):
    """The band ``cheme safety hazop rate`` looked up; never edited by hand."""

    value: str
    provenance: Literal["calculated"] = "calculated"
    source: str = Field(description="cheme safety hazop rate: <matrix id> (<matrix file>)")
    fingerprint: Identifier = Field(
        description="Of the matrix and the codes it was looked up from."
    )
    inputs: BandInputs | None = Field(
        default=None,
        description="What it was looked up from: the matrix fingerprint, the category and the "
        "codes (written since 0.9; a band without it is checked by its fingerprint alone).",
    )


class FrequencyRef(Strict):
    """Where a rating's likelihood comes from: one record of the study's frequency library, or
    an event type (its screening value: the highest of its records, LOPA initiating-event
    records first when there are any)."""

    record: str | None = None
    event_type: str | None = None

    @model_validator(mode="after")
    def _one(self) -> FrequencyRef:
        if (self.record is None) == (self.event_type is None):
            raise ValueError("give a record or an event_type")
        return self


class Rating(Strict):
    """Severity and likelihood of a scenario in one category: authored, with their basis."""

    category: str
    severity: Code | None = Field(default=None, description="None: not rated yet.")
    likelihood: Code | None = Field(
        default=None,
        description="None: not rated yet. With frequency: derived by cheme safety hazop rate "
        "--write from the study's frequency library and the matrix's max_frequency.",
    )
    frequency: FrequencyRef | None = Field(
        default=None, description="The frequency record or event type the likelihood rests on."
    )
    basis: str = Field(default="", description="Why these codes: the outcome, the frequency.")
    evidence: list[str] = Field(default_factory=list, description="Files, D-NNN, documents.")
    status: Judgement = "proposed"
    by: str = Field(default="", description="Who proposed or accepted it.")
    band: CalculatedBand | None = Field(
        default=None, description="Written by cheme safety hazop rate --write."
    )


class Risk(Strict):
    """A scenario's ratings: before its safeguards and, separately, with them."""

    initial: list[Rating] = Field(default_factory=list, description="Before the safeguards.")
    residual: list[Rating] = Field(
        default_factory=list,
        description="With the safeguards, as the team rates it (never derived from them).",
    )


class Scenario(Strict):
    """One cause of a deviation leading to one consequence: a worksheet row."""

    id: StableId
    cause: str = Field(min_length=1)
    consequence: str = ""
    refs: PlantRefs = Field(
        default_factory=list, description="Plant items of the cause and the consequence."
    )
    modes: list[str] = Field(default_factory=list, description="Operating mode ids; none: all.")
    safeguards: list[str] = Field(default_factory=list, description="Safeguard ids.")
    actions: list[str] = Field(default_factory=list, description="Action ids.")
    risk: Risk | None = None
    status: Judgement = "proposed"
    by: str = ""
    evidence: list[str] = Field(default_factory=list)
    notes: str = ""
    extensions: Extensions = Field(default_factory=dict)


class Deviation(Strict):
    """A guide word applied to a parameter of the node's design intent."""

    id: StableId | None = None
    guide_word: GuideWord
    parameter: str = Field(min_length=1, description="flow, pressure, temperature, level, ...")
    description: str = ""
    scenarios: list[Scenario] = Field(default_factory=list)
    notes: str = Field(default="", description="e.g. why no cause is credible.")


class Node(Strict):
    """A study node: a part of the plant with one design intent."""

    id: StableId
    title: str = ""
    design_intent: str = ""
    members: PlantRefs = Field(default_factory=list, description="The plant items of the node.")
    modes: list[str] = Field(default_factory=list, description="Operating mode ids; none: all.")
    deviations: list[Deviation] = Field(default_factory=list)
    status: Judgement = "proposed"
    by: str = ""
    notes: str = ""
    extensions: Extensions = Field(default_factory=dict)


class Safeguard(Strict):
    """Something that prevents a cause, or stops or mitigates its consequence."""

    id: StableId
    title: str = Field(min_length=1)
    kind: SafeguardKind = "other"
    refs: PlantRefs = Field(default_factory=list, description="Its devices: tags on the P&IDs.")
    interlock: Identifier | None = Field(
        default=None, description="Its id in control/cause-effect.yaml."
    )
    status: Judgement = "proposed"
    by: str = ""
    notes: str = ""


class Action(Strict):
    """A recommendation of the study and what became of it."""

    id: StableId
    text: str = Field(min_length=1)
    owner: str = ""
    due: datetime.date | None = None
    status: ActionStatus = "proposed"
    response: str = Field(default="", description="How it was closed, or why it was rejected.")
    by: str = ""


class Mode(Strict):
    """An operating mode the study covers."""

    id: StableId
    title: str = ""
    description: str = ""


class Member(Strict):
    name: str = Field(min_length=1)
    role: str = ""


class HazopStudy(Strict):
    """A HAZOP study: scope, analysed inputs, nodes, deviations, scenarios, safeguards, actions."""

    schema_: str = Field(alias="schema", description=f"Always {STUDY_SCHEMA}.")
    kind: Literal["hazop-study"]
    id: StableId = Field(description="The study's directory name under safety/hazop/.")
    title: str = ""
    example: bool = Field(
        default=False,
        description="True: an illustrative study, not an assessment of a plant (it stays a "
        "draft whatever it holds).",
    )
    scope: str = ""
    modes: list[Mode] = Field(default_factory=list)
    analysed: list[Basis] = Field(
        default_factory=list,
        description="The files the study analyses (P&IDs, control data), each at the revision "
        "analysed (sha256:<hex> or a commit); a later change asks for reassessment.",
    )
    risk_matrix: str | None = Field(
        default=None, description="The matrix file from the repository root."
    )
    frequencies: str | None = Field(
        default=None,
        description="The frequency library ratings link to (frequency:), from the repository "
        "root: project data, e.g. safety/frequencies.yaml (cheme schema frequencies).",
    )
    assessment_basis: str = Field(
        default="", description="How risk is ranked: initial and residual, what is credited."
    )
    team: list[Member] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    safeguards: list[Safeguard] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    notes: str = ""
    extensions: Extensions = Field(default_factory=dict)

    @field_validator("risk_matrix", "frequencies")
    @classmethod
    def _matrix_path(cls, value: str | None) -> str | None:
        if value is not None and (value.startswith("/") or ".." in value.split("/")):
            raise ValueError("give the file by its path from the repository root")
        return value

    @model_validator(mode="after")
    def _version(self) -> HazopStudy:
        if self.schema_ != STUDY_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, STUDY_SCHEMA))
        return self

    def scenarios(self) -> list[tuple[Node, Deviation, Scenario]]:
        """Every scenario with its node and deviation, in worksheet order."""
        return [(n, d, s) for n in self.nodes for d in n.deviations for s in d.scenarios]


# ---------------------------------------------------------------------------
# Coverage triage (safety/hazop/<id>/coverage.yaml)
# ---------------------------------------------------------------------------

#: ``open``: found by the walk, not looked at yet; ``dismissed``: needs no scenario, with the
#: reason; ``question``: the files do not settle it, for the team. Covered is never written:
#: ``--coverage`` derives it from the scenarios' refs.
TriageStatus = Literal["open", "dismissed", "question"]


class Outcome(Strict):
    """A top event the walk brings to a node that no scenario covers, and what was decided."""

    node: StableId
    guide_word: GuideWord
    parameter: str = Field(min_length=1)
    top_event: TopEvent
    at: str = Field(min_length=1, description="The tag or object id where the walk ends.")
    causes: list[str] = Field(
        default_factory=list, description="The causes (tags) it is about; none: every cause."
    )
    status: TriageStatus = "open"
    reason: str = Field(default="", description="Why dismissed, or what the question is.")
    judgement: Judgement = Field(
        default="proposed", description="accepted once the team agrees with the status."
    )
    by: str = ""

    @model_validator(mode="after")
    def _reasoned(self) -> Outcome:
        if self.status != "open" and not self.reason.strip():
            raise ValueError(f"status {self.status} needs its reason")
        return self


class Walk(Strict):
    """The inputs of the walk the outcomes were listed from (written by the tool)."""

    library: str = Field(description="sha256 of the failure-mode library.")
    sheets: dict[str, str] = Field(default_factory=dict, description="Sheet file -> sha256.")


class HazopCoverage(Strict):
    """The triage of a study's propagation outcomes: one entry per top event no scenario covers,
    written ``open`` by ``cheme safety hazop propagate --coverage --write``, decided by an agent
    or the team. Kept beside the study so the worksheet holds only its rows."""

    schema_: str = Field(alias="schema", description=f"Always {COVERAGE_SCHEMA}.")
    kind: Literal["hazop-coverage"]
    study: StableId
    walk: Walk | None = None
    outcomes: list[Outcome] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> HazopCoverage:
        if self.schema_ != COVERAGE_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, COVERAGE_SCHEMA))
        return self


# ---------------------------------------------------------------------------
# Failure-mode library (scenario propagation)
# ---------------------------------------------------------------------------

#: Which way a deviation travels along the piping from where it arises; ``none``: it stays at
#: the object (a level, a temperature inside), and the object's own responses to it apply.
Towards = Literal["downstream", "upstream", "both", "none"]
#: What an object does with a deviation reaching it: turns it into another (``responds``), lets
#: it through (``passes``, ``no-effect``: not recorded as a step), takes it up (``absorbs``) or
#: ends the chain at a top event (``stops``).
ResponseEffect = Literal["responds", "passes", "no-effect", "absorbs", "stops"]


class DeviationSpec(Strict):
    """A deviation: a guide word applied to a parameter, and which way it travels."""

    parameter: str = Field(min_length=1, description="flow, pressure, temperature, level, ...")
    guide_word: GuideWord
    towards: Towards = Field(
        default="downstream", description="Which way it travels along the piping from here."
    )


class FailureMode(Strict):
    """A way an object of the class can fail, and the deviation it gives at the object."""

    id: StableId
    gives: DeviationSpec
    mechanism: str = ""
    needs: Literal["power", "actuation", "operator"] | None = Field(
        default=None,
        description="actuation: only an object operated by an actuating system can fail so.",
    )
    fail: Literal["open", "closed", "last", "stop", "off"] | None = Field(
        default=None,
        description="Only where the object's fail position (control/loops.yaml) is this one; an "
        "unrecorded fail position keeps the mode, with a question.",
    )
    at: Literal["self", "final-element"] = Field(
        default="self",
        description="final-element: an instrument function's failure, felt at the valve it "
        "actuates.",
    )


class Response(Strict):
    """What an object of the class does with an incoming deviation."""

    incoming: DeviationSpec
    via: Literal["inlet", "outlet", "any"] = Field(
        default="any",
        description="inlet: the deviation arrives travelling downstream; outlet: upstream.",
    )
    effect: ResponseEffect
    gives: DeviationSpec | None = Field(default=None, description="The deviation it turns into.")
    top_event: TopEvent | None = None
    note: str = ""

    @model_validator(mode="after")
    def _complete(self) -> Response:
        if self.effect == "responds" and self.gives is None:
            raise ValueError("effect responds needs gives: the deviation it turns into")
        if self.effect == "stops" and self.top_event is None:
            raise ValueError("effect stops needs top_event")
        return self


class ClassEntry(Strict):
    """The failure modes and responses of one DEXPI class (and its subclasses)."""

    modes: list[FailureMode] = Field(default_factory=list)
    responses: list[Response] = Field(default_factory=list)


class FailureModeLibrary(Strict):
    """The project's failure modes and responses by DEXPI class: the data
    ``cheme safety hazop propagate`` walks the P&IDs with. Project data, written by the team."""

    schema_: str = Field(alias="schema", description=f"Always {FAILURE_MODES_SCHEMA}.")
    kind: Literal["failure-modes"]
    example: bool = Field(default=False, description="True: illustrative data, not a library.")
    status: Judgement = "proposed"
    source: str = Field(
        default="", description="Who wrote it and from what: the basis and licence of the content."
    )
    classes: dict[str, ClassEntry] = Field(
        default_factory=dict,
        description="By DEXPI class name (CentrifugalPump, Valve, ...): an object takes the "
        "entry of its most specific class that has one.",
    )
    notes: str = ""

    @model_validator(mode="after")
    def _version(self) -> FailureModeLibrary:
        if self.schema_ != FAILURE_MODES_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, FAILURE_MODES_SCHEMA))
        return self


# ---------------------------------------------------------------------------
# Frequency library (likelihood of a rating's cause)
# ---------------------------------------------------------------------------

#: ``lopa_ief``: a screening initiating-event frequency from LOPA guidance (conservative, order of
#: magnitude); ``qra_loc``: a generic loss-of-containment frequency from QRA guidance.
FrequencyBasis = Literal["lopa_ief", "qra_loc"]


class FrequencySource(Strict):
    """A source the records cite."""

    short: str = Field(min_length=1)
    citation: str = ""
    quoted_in: str = Field(default="", description="The secondary source it was read in.")
    url: str = ""
    year: int | None = None
    basis: FrequencyBasis | None = None
    notes: str = ""


class EventType(Strict):
    """A kind of initiating event the records are grouped by."""

    group: str = ""
    label: str = ""
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class FrequencyRecord(Strict):
    """One frequency of one event type from one source, as the source gives it."""

    id: StableId
    event_type: str
    value: float = Field(gt=0, description="Events per year, per one `per`.")
    per: str | None = Field(
        default=None,
        description="What the value is per when not one item (100 m of pipe, flanged joint): such "
        "a record gives no likelihood by itself.",
    )
    label: str = ""
    conditions: str = ""
    source: str = Field(description="A key of sources:.")
    locator: str = Field(default="", description="Table, row, page in the source.")
    verified: bool = Field(default=False, description="True once checked against the source.")
    notes: str = ""


class ModeEvent(Strict):
    """A failure mode of another library mapped to the event type it is an instance of."""

    id: str
    mode: str = ""
    applies_to: list[str] = Field(default_factory=list)
    event_type: str


class FrequencyLibrary(Strict):
    """The project's frequencies of initiating events, the likelihood basis of the ratings that
    link to them (Rating.frequency). Project data with its sources: cheme-as-code ships none."""

    schema_: str = Field(alias="schema", description=f"Always {FREQUENCIES_SCHEMA}.")
    kind: Literal["frequencies"]
    example: bool = Field(default=False, description="True: illustrative data, not a library.")
    source: str = Field(default="", description="Where the library comes from, and its licence.")
    sources: dict[str, FrequencySource] = Field(default_factory=dict)
    event_types: dict[str, EventType] = Field(default_factory=dict)
    records: list[FrequencyRecord] = Field(default_factory=list)
    modes: list[ModeEvent] = Field(
        default_factory=list, description="Failure mode -> event type, a help for choosing one."
    )
    notes: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> FrequencyLibrary:
        if self.schema_ != FREQUENCIES_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, FREQUENCIES_SCHEMA))
        ids = [r.id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError(
                f"record ids given twice: {sorted({i for i in ids if ids.count(i) > 1})}"
            )
        for record in self.records:
            if record.source not in self.sources:
                raise ValueError(
                    f"record {record.id}: source {record.source!r} is not under sources:"
                )
            if record.event_type not in self.event_types:
                raise ValueError(
                    f"record {record.id}: event_type {record.event_type!r} not under event_types:"
                )
        return self
