"""Versioned, simulator-independent file-worker exchange (ADR 0072).

Deployment details live in transport configuration, never in this project request.
Large or native assets are declared file paths, not JSON-embedded binary data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from chemeascode.foundation.project_paths import project_name
from chemeascode.foundation.schema_base import Strict


class Producer(Strict):
    tool: Literal["cheme process simulate"] = "cheme process simulate"
    adapter: str = Field(min_length=1)
    model: str = Field(min_length=1)


class Mappings(Strict):
    streams: dict[str, str] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    instruments: dict[str, str] = Field(default_factory=dict)


class WorkerRequest(Strict):
    """The declared inputs and assigned destination of one simulator worker execution."""

    schema_: Literal["cheme/worker-request/v1"] = Field(
        default="cheme/worker-request/v1", alias="schema"
    )
    run_id: str = Field(min_length=1)
    case: str = Field(min_length=1)
    mode: Literal["steady-state", "dynamic"]
    model: str
    input: str
    files: list[str]
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    mappings: Mappings = Field(default_factory=Mappings)
    timeout_s: float = Field(gt=0, le=3600, allow_inf_nan=False)
    evidence: str
    fingerprints: dict[str, str] = Field(default_factory=dict)

    @field_validator("input")
    @classmethod
    def primary_path(cls, value: str) -> str:
        return project_name(value)

    @field_validator("files")
    @classmethod
    def declared_paths(cls, values: list[str]) -> list[str]:
        return [project_name(value) for value in values]

    @model_validator(mode="after")
    def declared_primary(self):
        if self.input not in self.files or len(set(self.files)) != len(self.files):
            raise ValueError("Worker files must be unique and include the primary input")
        if not set(self.fingerprints) <= set(self.files):
            raise ValueError("Fingerprints may only name declared worker files")
        if any(
            not value.startswith("sha256:")
            or len(value) != 71
            or any(c not in "0123456789abcdef" for c in value[7:])
            for value in self.fingerprints.values()
        ):
            raise ValueError("Worker input fingerprints must be SHA-256 digests")
        return self


class ExecutionOutcome(Strict):
    state: Literal["completed", "failed", "timed-out", "refused"]
    transport: str
    exit_code: int | None = None
    elapsed_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    message: str = ""

    @model_validator(mode="after")
    def completed_exit(self):
        if self.state == "completed" and self.exit_code not in (None, 0):
            raise ValueError("A nonzero process exit cannot be a completed execution")
        return self


class IntegrationProgress(Strict):
    start: float = Field(allow_inf_nan=False)
    requested_end: float = Field(allow_inf_nan=False)
    achieved_end: float = Field(allow_inf_nan=False)
    time_unit: Literal["s", "min", "h", "day"]
    completed: bool

    @model_validator(mode="after")
    def interval(self):
        if not self.start <= self.achieved_end <= self.requested_end:
            raise ValueError("Integration times must satisfy start <= achieved <= requested end")
        if self.completed != (self.achieved_end == self.requested_end):
            raise ValueError("Completion must agree with the achieved end time")
        return self


class SteadyStateAssessment(Strict):
    state: Literal["established", "not-established", "not-evaluated"] = "not-evaluated"
    evidence: list[str] = Field(default_factory=list)
    method: str | None = None

    @field_validator("evidence")
    @classmethod
    def paths(cls, values: list[str]) -> list[str]:
        return [project_name(value) for value in values]

    @model_validator(mode="after")
    def supported_claim(self):
        if self.state == "established" and (not self.evidence or not self.method):
            raise ValueError("An established steady state requires a method and evidence")
        return self


class NumericalOutcome(Strict):
    mode: Literal["steady-state", "dynamic"]
    convergence: Literal["converged", "not-converged", "not-applicable", "unknown"] = "unknown"
    integration: IntegrationProgress | None = None
    steady_state: SteadyStateAssessment = Field(default_factory=SteadyStateAssessment)

    @model_validator(mode="after")
    def mode_interval(self):
        if self.mode == "steady-state" and self.integration is not None:
            raise ValueError("Steady-state solves must not claim a dynamic integration interval")
        return self


class VariableReference(Strict):
    kind: Literal["stream", "unit", "instrument"]
    id: str = Field(min_length=1)
    quantity: str | None = None


class TrajectoryVariable(Strict):
    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    reference: VariableReference | None = None


class FinalSnapshot(Strict):
    time: float = Field(allow_inf_nan=False)
    selection: Literal["last-row"] = "last-row"
    interpretation: Literal["instantaneous"] = "instantaneous"


class Trajectory(Strict):
    """A CSV time series with units, stable references and a final instantaneous snapshot."""

    schema_: Literal["cheme/trajectory/v1"] = Field(default="cheme/trajectory/v1", alias="schema")
    path: str
    format: Literal["csv"] = "csv"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    time_variable: str = Field(min_length=1)
    time_unit: Literal["s", "min", "h", "day"]
    start: float = Field(allow_inf_nan=False)
    end: float = Field(allow_inf_nan=False)
    variables: list[TrajectoryVariable] = Field(min_length=1)
    event_side_column: str | None = None
    final_snapshot: FinalSnapshot

    @field_validator("path")
    @classmethod
    def artifact_path(cls, value: str) -> str:
        return project_name(value)

    @model_validator(mode="after")
    def columns_and_interval(self):
        names = [self.time_variable, *(v.name for v in self.variables)]
        if self.event_side_column:
            names.append(self.event_side_column)
        if len(names) != len(set(names)):
            raise ValueError("Trajectory columns must be unique")
        if self.end < self.start or self.final_snapshot.time != self.end:
            raise ValueError("Final instantaneous snapshot must select the trajectory end")
        return self
