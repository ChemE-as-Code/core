"""Validate bounded trajectory metadata and referenced evidence before publication."""

import csv
import hashlib
import json
import math

from chemeascode.foundation.project_paths import local_path
from chemeascode.integrations.workers import evidence_files


def validate(result, request, evidence, identities):
    evidence_files(evidence)
    json.dumps(result.as_dict(), allow_nan=False)
    if result.case != request.case or result.outcome is None or result.outcome.mode != request.mode:
        raise ValueError("Worker returned a different case or execution mode")
    if result.execution is None or result.execution.state != "completed":
        raise ValueError("Worker execution did not complete")
    if any(f.get("level") == "error" for f in result.findings):
        raise ValueError("Worker reported error findings")
    if result.outcome.mode == "dynamic":
        progress = result.outcome.integration
        if result.status != "completed" or progress is None or not progress.completed:
            raise ValueError("Partial or unsuccessful integration cannot publish scalar results")
    elif result.status != "converged" or result.outcome.convergence != "converged":
        raise ValueError("Steady-state solve has not reported numerical convergence")
    for rows, kind in ((result.streams, "stream"), (result.units, "unit")):
        names = [row.id for row in rows]
        if len(names) != len(set(names)) or not set(names) <= identities[kind]:
            raise ValueError(f"Unexpected or duplicate {kind} identities")
    for name in result.outcome.steady_state.evidence:
        if not local_path(evidence, name).is_file():
            raise ValueError(f"Missing steady-state assessment evidence: {name}")
    paths = [item.path for item in result.trajectories]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate trajectory artifact")
    for item in result.trajectories:
        if request.mode != "dynamic":
            raise ValueError("Time trajectories require dynamic mode")
        path = local_path(evidence, item.path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
            raise ValueError(f"Missing or changed trajectory: {item.path}")
        for variable in item.variables:
            ref = variable.reference
            if ref and ref.id not in identities[ref.kind]:
                raise ValueError(f"Unknown trajectory {ref.kind}: {ref.id}")
        columns = [item.time_variable, *(v.name for v in item.variables)]
        all_columns = [*columns, *([item.event_side_column] if item.event_side_column else [])]
        first, previous, previous_side, last = None, None, None, None
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if (
                reader.fieldnames is None
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or set(reader.fieldnames) != set(all_columns)
            ):
                raise ValueError("Trajectory columns differ from the manifest")
            for row in reader:
                if None in row or any(row.get(name) is None for name in all_columns):
                    raise ValueError("Malformed trajectory row")
                values = {name: float(row[name]) for name in columns}
                if not all(math.isfinite(value) for value in values.values()):
                    raise ValueError("Trajectory contains non-finite values")
                time = values[item.time_variable]
                side = row[item.event_side_column] if item.event_side_column else None
                if side is not None and side not in {"before", "after", "sample"}:
                    raise ValueError("Unknown trajectory event side")
                if previous is not None and (
                    time < previous
                    or (time == previous and (previous_side, side) != ("before", "after"))
                ):
                    raise ValueError(
                        "Trajectory times must increase; duplicate events need before/after sides"
                    )
                if first is None:
                    first = time
                previous, previous_side, last = time, side, values
        if first != item.start or previous != item.end or last is None:
            raise ValueError("Trajectory interval differs from its data")
        progress = result.outcome.integration
        if (
            item.time_unit != progress.time_unit
            or item.start != progress.start
            or item.end != progress.achieved_end
        ):
            raise ValueError("Trajectory interval differs from the integration outcome")
        for variable in item.variables:
            ref = variable.reference
            if ref and ref.kind == "stream" and ref.quantity:
                row = next((row for row in result.streams if row.id == ref.id), None)
                cell = row.values.get(ref.quantity) if row else None
                if (
                    not isinstance(cell, dict)
                    or cell.get("unit") != variable.unit
                    or cell.get("value") != last[variable.name]
                ):
                    raise ValueError(
                        "Published scalar must equal the declared final instantaneous snapshot"
                    )
