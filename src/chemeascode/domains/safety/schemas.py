"""Schemas of the safety files: the risk matrix (``cheme/risk-matrix/v1``) and the HAZOP study
(``cheme/hazop-study/v1``, ``safety/hazop/<study-id>/study.yaml``).

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


class Rating(Strict):
    """Severity and likelihood of a scenario in one category: authored, with their basis."""

    category: str
    severity: Code | None = Field(default=None, description="None: not rated yet.")
    likelihood: Code | None = Field(default=None, description="None: not rated yet.")
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
    assessment_basis: str = Field(
        default="", description="How risk is ranked: initial and residual, what is credited."
    )
    team: list[Member] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    safeguards: list[Safeguard] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    notes: str = ""
    extensions: Extensions = Field(default_factory=dict)

    @field_validator("risk_matrix")
    @classmethod
    def _matrix_path(cls, value: str | None) -> str | None:
        if value is not None and (value.startswith("/") or ".." in value.split("/")):
            raise ValueError("give the matrix by its path from the repository root")
        return value

    @model_validator(mode="after")
    def _version(self) -> HazopStudy:
        if self.schema_ != STUDY_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, STUDY_SCHEMA))
        return self

    def scenarios(self) -> list[tuple[Node, Deviation, Scenario]]:
        """Every scenario with its node and deviation, in worksheet order."""
        return [(n, d, s) for n in self.nodes for d in n.deviations for s in d.scenarios]
