"""The adapter result (``cheme/adapter-result/v1``): what one run of a model or solver adapter
gave for one case, in the same shape whichever adapter ran it (docs/framework/contract.md).

Emitted by ``cheme process simulate --fill`` (DWSIM; each entry of
``process/simulation-run.json``), ``cheme process propagate --json`` and ``cheme process props
--json``. ``status`` is ``converged`` (the adapter solved what it was given), ``not-converged``
(it ran and left something unsolved; ``messages`` says what), ``refused`` (it did not start: an
input it does not support) or ``failed`` (it started and broke off). ``iterations`` is null
where the solver does not report one.

The DWSIM run record predates this model: its entries name the solver ``simulator`` and carry
``converged``, and entries written before the model have no ``status``; both are read here
(``status`` then follows ``converged``). ``schema`` is the default where an entry sits inside
a file with its own ``schema`` (``cheme/simulation-run/v1``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from chemeascode.foundation.findings import Finding

ADAPTER_SCHEMA = "cheme/adapter-result/v1"
AdapterStatus = Literal["converged", "not-converged", "refused", "failed"]


class Solver(BaseModel):
    """The solver that ran."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: str | None = None
    method: str | None = Field(
        default=None, description="The property package, equation of state or rule set."
    )


class Revision(BaseModel):
    """The inputs as they were (``foundation.provenance.SourceRevision.as_dict``)."""

    model_config = ConfigDict(extra="allow")

    commit: str | None = None
    dirty: list[str] = Field(default_factory=list)
    fingerprints: dict[str, str] = Field(default_factory=dict)


class UnitResult(BaseModel):
    """One step or block: ``status`` simulated, excluded, not-solved, ..."""

    model_config = ConfigDict(extra="allow")

    id: str
    status: str
    converged: bool | None = None
    results: dict[str, Any] = Field(default_factory=dict)


class StreamResult(BaseModel):
    """One stream: the values the adapter calculated, and those it wrote (``filled``)."""

    model_config = ConfigDict(extra="allow")

    id: str
    values: dict[str, Any] = Field(default_factory=dict)
    filled: list[str] = Field(default_factory=list)


class AdapterResult(BaseModel):
    """One run of an adapter for one case."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_: Literal["cheme/adapter-result/v1"] = Field(default=ADAPTER_SCHEMA, alias="schema")
    case: str
    status: AdapterStatus
    solver: Solver = Field(validation_alias=AliasChoices("solver", "simulator"))
    model_fingerprint: str | None = Field(
        default=None,
        description="The fingerprint of the translated inputs; null where the adapter "
        "fingerprints each value instead.",
    )
    inputs: Revision = Field(default_factory=Revision)
    iterations: int | None = None
    messages: list[str] = Field(default_factory=list)
    units: list[UnitResult] = Field(default_factory=list)
    streams: list[StreamResult] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _status_of_converged(cls, data: Any) -> Any:
        """A DWSIM entry without ``status`` (written before this model): from ``converged``."""
        if isinstance(data, dict) and "status" not in data and "converged" in data:
            data = {**data, "status": "converged" if data["converged"] else "not-converged"}
        return data

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready, ``schema`` first."""
        return self.model_dump(mode="json", by_alias=True)


def finding_dict(finding: Finding) -> dict[str, Any]:
    """A finding as the results record it."""
    return {
        "file": finding.file,
        "line": finding.line,
        "level": finding.level,
        "rule": finding.rule,
        "message": finding.message,
        "ids": list(finding.ids),
        "hint": finding.hint,
        "id": finding.id,
    }
