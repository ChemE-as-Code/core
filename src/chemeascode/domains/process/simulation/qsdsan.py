"""QSDsan semantics and the bounded legacy A2/O response translation (ADR 0072).

Execution, provenance and publication belong to the shared worker path. No QSDsan
installation is imported by core, including when reading historical run records.
"""

import csv
import hashlib
import json

from chemeascode.domains.process.simulation import SOURCE
from chemeascode.foundation.schemas.run import AdapterResult
from chemeascode.foundation.schemas.worker import FinalSnapshot, Trajectory, TrajectoryVariable

from .worker_adapters import ProjectAdapter


class QSDsanAdapter(ProjectAdapter):
    def __init__(self):
        super().__init__(
            id="qsdsan",
            title="QSDsan",
            modes=("dynamic",),
            configuration_name="qsdsan",
            interpreter_variable="CHEME_QSDSAN_PYTHON",
        )

    def legacy_source(self, config):
        return f"{SOURCE}: QSDsan {config.model}"

    def normalize(self, result, request, evidence):
        if result.schema_ == "cheme/adapter-result/v2":
            return super().normalize(result, request, evidence)
        if result.solver.name != self.title or result.status != "converged":
            raise ValueError("Worker returned a different solver or unsuccessful result")
        # The published A2/O v1 worker reports the interval and checks in result.json.
        # Do not infer completion from exit zero, a legacy flag or a final-window screen.
        path = evidence / "result.json"
        if not path.is_file():
            raise ValueError("Legacy QSDsan result needs result.json with integration evidence")
        saved = json.loads(path.read_bytes())
        declared = json.loads((evidence / "cheme-inputs" / request.input).read_bytes())
        if (
            not isinstance(saved, dict)
            or not isinstance(declared, dict)
            or any(
                not isinstance(saved.get(k), dict)
                for k in ("basic_checks", "solver", "metric_units")
            )
            or not isinstance(declared.get("solver"), dict)
        ):
            raise ValueError("Legacy QSDsan integration evidence is malformed")
        if (
            saved.get("case_id") != request.case
            or declared.get("case_id") != request.case
            or saved.get("status") != "completed"
            or saved.get("basic_checks", {}).get("integration_reached_requested_day") is not True
            or saved.get("solver", {}).get("days") != declared.get("solver", {}).get("days")
        ):
            raise ValueError("Legacy QSDsan integration completion is not established")
        trajectory = evidence / "trajectory.csv"
        with trajectory.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("Legacy QSDsan trajectory is empty")
        start, end = float(rows[0]["day"]), float(rows[-1]["day"])
        if start != 0:
            raise ValueError("Legacy A2/O integration must start at day zero")
        manifest = Trajectory(
            path="trajectory.csv",
            sha256=hashlib.sha256(trajectory.read_bytes()).hexdigest(),
            time_variable="day",
            time_unit="day",
            start=start,
            end=end,
            variables=[
                TrajectoryVariable(name=name, unit=unit)
                for name, unit in saved["metric_units"].items()
            ],
            final_snapshot=FinalSnapshot(time=end),
        )
        data = result.as_dict()
        data.update(
            schema="cheme/adapter-result/v2",
            status="completed",
            trajectories=[manifest.model_dump(by_alias=True)],
            outcome={
                "mode": "dynamic",
                "convergence": "not-applicable",
                "integration": {
                    "start": start,
                    "requested_end": saved["solver"]["days"],
                    "achieved_end": end,
                    "time_unit": "day",
                    "completed": True,
                },
                "steady_state": {"state": "not-evaluated"},
            },
        )
        data["messages"].append(
            "Legacy A2/O integration evidence translated; steady state is not established."
        )
        return AdapterResult.model_validate(data)
