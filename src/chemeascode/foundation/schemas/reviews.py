"""``reviews/<YYYY-MM-DD>-<topic>.md``: the YAML front matter of a review record."""

import datetime
from typing import Literal

from pydantic import Field, field_validator

from chemeascode.foundation.schema_base import Strict, _identifier, optional_schema

#: Who reviewed: a person, an agent other than the author, or the author itself.
ReviewerKind = Literal["human", "agent", "self"]

#: How an artifact relates to a source it records (``chemeascode.foundation.provenance``).
Relation = Literal["derived-from", "represents", "analyses", "depends-on"]


class Basis(Strict):
    """One source an artifact rests on, at the revision it was looked at."""

    path: str = Field(
        min_length=1, description="File or directory from the repository root (process/)."
    )
    revision: str = Field(
        description="A commit sha, or sha256:<hex> of the file's content, when it was used."
    )
    relation: Relation = Field(
        default="depends-on",
        description="derived-from, represents, analyses or depends-on.",
    )

    @field_validator("revision", mode="before")
    @classmethod
    def _revision(cls, value: object) -> object:
        return _identifier(value)


class ReviewRecord(Strict, optional_schema("review")):
    """Front matter of a review record: YAML between two --- lines at the top of the file."""

    topic: str = Field(description="What was reviewed, e.g. design, o2-safety, hazop.")
    reviewed_commit: str = Field(description="The commit whose files were reviewed (a sha).")
    scope: list[str] = Field(
        min_length=1,
        description="Files or directories reviewed, from the repository root (pid/P-03.xml).",
    )
    reviewer: str = Field(min_length=1, description="Name of the person or agent.")
    reviewer_kind: ReviewerKind = Field(
        description="human, agent (independent of the author) or self (the author's own review)."
    )
    date: datetime.date | None = None
    branch: str | None = Field(default=None, description="Branch the reviewed work is on.")
    merge: str | None = Field(
        default=None, description="Merge commit to the default branch, or 'pending'."
    )
    approved_by: str | None = Field(
        default=None, description="A human who approved the record (needed for a self review)."
    )
    notes: str = ""
    basis: list[Basis] = Field(
        default_factory=list,
        description="Other sources the review rests on, outside its scope, each with the "
        "revision used; cheme impact flags the record when one has changed since.",
    )

    @field_validator("reviewed_commit", mode="before")
    @classmethod
    def _sha(cls, value: object) -> object:
        return _identifier(value)

    @field_validator("topic", "reviewer")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()
