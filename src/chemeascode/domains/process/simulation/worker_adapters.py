"""Small extension interface for project models; no simulator SDK is imported here.

An adapter selects model semantics and publication shape. A transport only runs it.
Register actual implementations in ``backends.BACKENDS``; names alone are not capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from chemeascode.foundation.schemas.run import AdapterResult
from chemeascode.foundation.schemas.worker import Producer, WorkerRequest
from chemeascode.integrations.workers import LocalPythonTransport, WorkerTransport, interpreter

if TYPE_CHECKING:
    from .schema import WorkerConfiguration


@dataclass(frozen=True)
class ProjectAdapter:
    id: str
    title: str
    modes: tuple[str, ...] = ("dynamic", "steady-state")
    publication: Literal["measured", "molecular"] = "measured"
    configuration_name: str = "worker"
    interpreter_variable: str = "CHEME_WORKER_PYTHON"

    def validate_configuration(self, config: WorkerConfiguration) -> None:
        if config.mode not in self.modes:
            raise ValueError(f"{self.title} does not support mode {config.mode}")
        if config.options:
            raise ValueError(f"{self.title} does not declare any additional worker options")

    def producer(self, config: WorkerConfiguration) -> Producer:
        return Producer(adapter=self.id, model=config.model)

    def legacy_source(self, config: WorkerConfiguration) -> str | None:
        return None

    def transport(self, config: WorkerConfiguration) -> WorkerTransport:
        if config.worker is None:
            raise ValueError("Local Python execution requires a declared worker module")
        return LocalPythonTransport(interpreter(self.interpreter_variable), config.worker)

    def normalize(
        self, result: AdapterResult, request: WorkerRequest, evidence: Path
    ) -> AdapterResult:
        if result.solver.name != self.title:
            raise ValueError("Worker returned a different solver")
        if result.schema_ != "cheme/adapter-result/v2":
            raise ValueError("This adapter requires cheme/adapter-result/v2 numerical outcomes")
        return result
