"""``runs/<run-id>/run.yaml``: the record of one design session (schema ``process-run/v1``).

One folder per run, never edited after it is written: a revision is a new run. Beside
``run.yaml`` the folder holds ``task.md`` (what the session was asked), ``report.md`` (what it
reported, optional) and ``session.jsonl.gz`` (the session transcript, when it may be published).
A value nobody knows is null, never estimated; ``complete`` is false when a fact is missing and
``incomplete_notes`` says which and why. ``cheme runs record`` writes it (ADR 0029).
"""

import datetime
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field

from chemeascode.foundation.schema_base import Strict

RUN_SCHEMA = "process-run/v1"
#: ``YYYYMMDD-HHMMSS`` of the start (UTC), then optionally ``-<slug>``.
RUN_ID_PATTERN = r"^\d{8}-\d{6}(-[a-z0-9][a-z0-9-]*)?$"

RunKind = Literal["agent", "interactive", "manual"]


def _iso(value: Any) -> Any:
    """A time YAML read as a datetime (unquoted) is the same time as its ISO text."""
    return value.isoformat() if isinstance(value, datetime.datetime | datetime.date) else value


Timestamp = Annotated[str, BeforeValidator(_iso)]


class Tokens(Strict):
    """Tokens of the session, each API message counted once."""

    input: int | None = None
    output: int | None = None
    thinking: int | None = Field(default=None, description="Null when never reported.")
    cache_read: int | None = None
    cache_write: int | None = None


class SessionExport(Strict):
    """The transcript in the run folder: gzip (mtime 0) of the JSONL."""

    file: str = Field(description="session.jsonl.gz")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Of the gzip bytes.")


class Runner(Strict):
    """The external program that ran the session (as it says about itself)."""

    name: str | None = None
    commit: str | None = Field(default=None, description="Its commit, when it knows one.")
    dirty: bool | None = Field(default=None, description="Uncommitted changes in its checkout.")


class Tools(Strict):
    """The software that produced the run; a version nobody knows is null."""

    cheme: str | None = Field(default=None, description="cheme-as-code version.")
    core_commit: str | None = Field(
        default=None,
        description="Commit of the installed cheme-as-code: from git, or HEAD of the source "
        "checkout of an editable or local install.",
    )
    core_dirty: bool | None = Field(
        default=None, description="Uncommitted changes in that checkout (untracked files count)."
    )
    pydexpi: str | None = Field(default=None, description="pyDEXPI version.")
    claude_code: str | None = Field(
        default=None, description="Claude Code version: the transcript's, else `claude --version`."
    )
    claude_agent_sdk: str | None = Field(
        default=None, description="Claude Agent SDK version, as the runner passed it."
    )
    runner: Runner | None = Field(default=None, description="The runner, when one passed it.")
    same_revision: bool | None = Field(
        default=None,
        description="True when cheme-as-code and the runner ran from the same clean commit; False "
        "when the commits differ or either checkout had changes; null when either is unknown.",
    )


class CheckAfterRun(Strict):
    """A check run by the recorder at the end of the session."""

    command: str
    exit: int
    summary: dict[str, Any] = Field(default_factory=dict)


class Outcome(Strict):
    """How the session ended."""

    result: str | None = Field(default=None, description="e.g. success, error_max_turns.")
    report: str | None = Field(default=None, description="report.md when there is one.")


class RunRecord(Strict):
    """Record of one design session: who ran it, on which commits, at what cost, with what."""

    schema_: Literal["process-run/v1"] = Field(alias="schema", description=RUN_SCHEMA)
    run_id: str = Field(pattern=RUN_ID_PATTERN, description="Also the folder name.")
    process: str = Field(description="The plant repository's folder name.")
    kind: RunKind = Field(description="agent, interactive or manual.")
    complete: bool = Field(description="False when any fact below is missing.")
    incomplete_notes: list[str] = Field(default_factory=list)
    task_file: str | None = Field(default=None, description="Where task.md was copied from.")
    branch: str | None = None
    start_commit: str | None = Field(default=None, description="HEAD at the session's start.")
    end_commit: str | None = Field(
        default=None, description="HEAD at the end, before the record's own commit."
    )
    started: Timestamp | None = None
    finished: Timestamp | None = None
    wall_s: float | None = None
    cost_usd: float | None = Field(default=None, description="Only as reported, never estimated.")
    cost_source: Literal["api"] | None = None
    budget_usd: float | None = None
    model: str | None = None
    effort: str | None = None
    num_turns: int | None = Field(default=None, description="Distinct assistant API messages.")
    tokens: Tokens | None = None
    session_id: str | None = None
    session_export: SessionExport | None = None
    tools: Tools = Field(default_factory=Tools)
    checks_by_agent: list[str] = Field(
        default_factory=list, description="Distinct cheme commands the session ran."
    )
    checks_after_run: list[CheckAfterRun] = Field(default_factory=list)
    outcome: Outcome = Field(default_factory=Outcome)
    observed_later: dict[str, Any] = Field(default_factory=dict)
