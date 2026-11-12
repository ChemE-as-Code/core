"""The bounded A2/O route of process simulate; wastewater results keep their own units."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from chemeascode.domains.process.fill import PropsResult
from chemeascode.domains.process.simulation import SIMULATION_FILE, record
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import source_revision, value_fingerprint
from chemeascode.foundation.schemas.run import AdapterResult, finding_dict
from chemeascode.integrations.qsdsan import execute, recipe_files


def fingerprint(fingerprints: dict[str, str]) -> str:
    return value_fingerprint({"adapter": "wwtp-a2o/v1", "files": fingerprints})


def run(root: Path, case: str, sim: Any, *, write: bool, save: Path | None) -> PropsResult:
    """Use the example's unchanged calculation; a successful integration is not steady state."""
    result = PropsResult()

    def finding(level, rule, message, hint):
        result.findings.append(Finding(SIMULATION_FILE, level, rule, message, hint=hint))

    try:
        if save is not None:
            raise ValueError("--save is DWSIM-only; QSDsan --fill already retains every run")
        config = sim.qsdsan
        source = source_revision(root, recipe_files(root, config.input)).as_dict()
        current = fingerprint(source["fingerprints"])
        previous = record.entry_of(record.read(root), case)
        if not write:
            if previous is None:
                finding(
                    "info",
                    "cheme.process-sim-run-missing",
                    "No saved QSDsan run for this case",
                    "Use --fill to retain a run after reviewing the input settings.",
                )
            elif previous.get("model_fingerprint") != current:
                finding(
                    "warning",
                    "cheme.process-sim-run-stale",
                    "Saved QSDsan inputs have changed",
                    "Review the changed source files and use --fill for a new record.",
                )
        worker = execute(
            root,
            environment=config.environment,
            input_path=config.input,
            case=case,
            timeout=config.timeout_s,
            write=write,
        )
        payload = worker.payload
        if worker.returncode or payload.get("status") != "completed":
            raise ValueError(
                f"QSDsan run failed: {payload.get('error', 'worker did not complete')}; "
                f"evidence: {payload.get('run', 'none')}. " + worker.stderr[-1000:]
            )
        adapter = AdapterResult.model_validate(payload["adapter"])
        if adapter.case != case or adapter.solver.name != "QSDsan" or adapter.status != "converged":
            raise ValueError(
                "QSDsan worker returned a different case, solver or unsuccessful result"
            )
        if any(s.filled for s in adapter.streams):
            raise ValueError("QSDsan must not fill molecular stream fields")
        entry = adapter.as_dict()
        # The worker refreshes generated project documents; fingerprint their final bytes.
        if write:
            after = source_revision(root, recipe_files(root, config.input)).as_dict()
            generated = {
                "plant.yaml",
                "process/flowsheet.yaml",
                "process/materials.yaml",
                "process/case-inputs.json",
            }
            before_inputs = {k: v for k, v in source["fingerprints"].items() if k not in generated}
            after_inputs = {k: v for k, v in after["fingerprints"].items() if k not in generated}
            if before_inputs != after_inputs:
                raise ValueError("Recipe changed during execution; retained run was not accepted")
            source = after
        entry.update(
            inputs=source,
            model_fingerprint=fingerprint(source["fingerprints"]),
            run_at=datetime.now(UTC).isoformat(),
            integration_completed=True,
            converged=True,
            simulator=entry.pop("solver"),
            property_package=None,
            tool="cheme-as-code " + version("cheme-as-code"),
        )
        result.adapter = AdapterResult.model_validate(entry)
        result.lines += [
            f"QSDsan A2/O: {case}; requested integration completed; basic checks passed.",
            "Completion is not a steady-state, conservation or plant-validation claim.",
        ]
        effluent = next((s for s in adapter.streams if s.id == "EFFLUENT"), None)
        if effluent:
            result.lines.extend(
                f"  {k}: {v['value']:.10g} {v['unit']}" for k, v in effluent.values.items()
            )
        if write:
            run_path = Path(payload["run"]).resolve()
            if not run_path.is_relative_to((root / "runs").resolve()) or not run_path.is_dir():
                raise ValueError("QSDsan run evidence is not in this project's runs folder")
            entry["evidence"] = run_path.relative_to(root).as_posix()
            text = json.dumps(entry, indent=2, ensure_ascii=False, allow_nan=False)
            (run_path / "cheme-simulation-entry.json").write_text(text, encoding="utf-8")
            (run_path / "cheme-worker.log").write_text(
                worker.stdout + worker.stderr, encoding="utf-8"
            )
            record.write(root, entry)
            (root / "runs/latest.json").write_text(
                json.dumps({"run_id": run_path.name}),
                encoding="utf-8",
            )
            result.lines += [
                f"Evidence: {run_path}",
                f"Report: {run_path / 'report.html'}",
                f"Run record: {root / record.RUN_FILE}",
            ]
        else:
            result.lines.append(
                "Check only: temporary calculation discarded; project files unchanged."
            )
    except (ValueError, OSError, KeyError, TypeError, ValidationError) as failure:
        finding(
            "error",
            "cheme.process-qsdsan",
            str(failure),
            "Inspect process/simulation.yaml, the process README and any retained run error.log.",
        )
    return result


def view(process, sim, data, case, fingerprints, problem="") -> dict:
    """Read-only native viewer result; no DWSIM translation or simulation is performed."""
    cases = (
        [c.id for c in process.flowsheet.cases]
        if process
        else sorted((data or {}).get("cases", {}))
    )
    case = case or (
        process.flowsheet.default_case() if process else (cases[0] if len(cases) == 1 else None)
    )
    entry = record.entry_of(data, case) if case else None
    stale = record.staleness(entry, fingerprint(fingerprints), fingerprints)
    if process is None:
        stale["stale"] = None
    return {
        "file": SIMULATION_FILE,
        "run_file": record.RUN_FILE,
        "case": case,
        "cases": cases,
        "spec": {
            "simulator": "qsdsan",
            "property_package": None,
            "qsdsan": sim.qsdsan.model_dump(mode="json"),
            "specs": {},
            "components": {},
            "tolerance": {},
            "tear_streams": [],
            "exclude": [],
            "guesses": {},
        },
        "run": entry,
        "stale": stale.pop("stale"),
        "staleness": stale,
        "units": [
            {
                "id": u["id"],
                "status": u["status"],
                "run": u,
                "unit": None,
                "reason": "Dynamic ASM2d calculation; see the separate verification statuses.",
                "spec": None,
            }
            for u in (entry or {}).get("units", [])
        ],
        "problem": problem or None,
        "findings": [
            finding_dict(
                Finding(
                    SIMULATION_FILE,
                    "info",
                    "cheme.process-qsdsan-scope",
                    "QSDsan completion means integration and basic checks, "
                    "not steady state or plant validation.",
                    hint="Read the wastewater report and its separate verification statuses.",
                )
            )
        ],
    }
