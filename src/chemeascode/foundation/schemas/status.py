"""``checks/status.json``: the stage sign-offs, written by ``cheme check --stage S --write``."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chemeascode.foundation.schema_base import optional_schema


class CheckResult(BaseModel):
    """One gate as it was evaluated."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    stage: str = ""
    status: str = Field(description="pass, fail or n/a.")
    detail: str = ""
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="What the gate rests on; a review gate: path, reviewed_commit, reviewer, "
        "reviewer_kind.",
    )


class SignOff(BaseModel):
    """The sign-off of one stage."""

    model_config = ConfigDict(extra="allow")

    stage: str
    commit: str = Field(description="The commit whose (clean) tree the gates were run on.")
    date: str = Field(description="When, ISO 8601 UTC.")
    signed_by: str
    branch: str | None = Field(default=None, description="Branch the sign-off was made on.")
    default_branch: str | None = None
    review: str | None = Field(default=None, description="Review record the sign-off rests on.")
    review_commit: str | None = Field(default=None, description="Its reviewed_commit.")
    reviewer: str | None = None
    reviewer_kind: str | None = None
    stages: list[str] = Field(
        default_factory=list, description="The stages whose gates were evaluated (up to stage)."
    )
    checks: list[CheckResult] = Field(default_factory=list)


class StatusFile(optional_schema("status")):
    """Stage sign-offs by stage id; ``checks`` repeats the gates of the latest sign-off."""

    model_config = ConfigDict(extra="allow")

    stages: dict[str, SignOff] = Field(default_factory=dict)
    checks: list[CheckResult] = Field(default_factory=list)
