"""Project-worker orchestration shared by simulator adapters (ADR 0072)."""

import json
import shutil
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.fill import PropsResult
from chemeascode.domains.process.simulation import SIMULATION_FILE, record, worker_model
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.provenance import source_revision
from chemeascode.foundation.schemas.run import AdapterResult, Solver
from chemeascode.foundation.schemas.worker import ExecutionOutcome, WorkerRequest
from chemeascode.foundation.workspace import Workspace
from chemeascode.integrations.workers import evidence_files

from . import worker_evidence, worker_publication


def _identities(process):
    instruments = Workspace(process.root).parsed_lists(("instruments",)).get("instruments")
    return {
        "stream": {s.id for s in process.flowsheet.streams},
        "unit": {n.id for n in [*process.flowsheet.steps, *process.flowsheet.blocks]},
        "instrument": {i.tag for i in instruments.instruments} if instruments else set(),
    }


def _mappings(request, identities):
    for kind in identities:
        mapping = getattr(request.mappings, kind + "s")
        if not set(mapping.values()) <= identities[kind] or len(mapping.values()) != len(
            set(mapping.values())
        ):
            raise ValueError(f"Invalid or ambiguous {kind} mapping")


def _map_results(result, request):
    """Native result identifiers become stable process identifiers exactly once."""
    for kind, rows in (("streams", result.streams), ("units", result.units)):
        mapping = getattr(request.mappings, kind)
        if mapping:
            for row in rows:
                if row.id not in mapping:
                    raise ValueError(f"Unmapped native {kind} identifier: {row.id}")
                row.id = mapping[row.id]
    for trajectory in result.trajectories:
        for variable in trajectory.variables:
            ref = variable.reference
            if ref:
                mapping = getattr(request.mappings, ref.kind + "s")
                if mapping:
                    if ref.id not in mapping:
                        raise ValueError(f"Unmapped trajectory identifier: {ref.id}")
                    ref.id = mapping[ref.id]


def _failed_attempt(root, evidence, request, execution, message):
    """Diagnostic evidence never replaces an accepted case entry or stream value."""
    folder = local_path(root, "process/simulation-attempts")
    if folder != root.resolve() / "process/simulation-attempts":
        raise ValueError("Refusing linked attempt storage")
    folder.mkdir(exist_ok=True)
    target = folder / evidence.name
    # Refused unsafe evidence is not copied; still retain the assigned outcome and reason.
    try:
        evidence_files(evidence)
    except ValueError:
        target.mkdir()
    else:
        shutil.copytree(evidence, target)
    (target / "cheme-attempt.json").write_text(
        json.dumps(
            {
                "schema": "cheme/worker-attempt/v1",
                "request": request.model_dump(mode="json", by_alias=True),
                "execution": execution.model_dump(),
                "accepted": False,
                "reason": message,
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    return target


def _worker_findings(response, adapter):
    """The findings the worker reported, located at the simulation: an unknown level counts
    as a warning, so ``--check`` exits 1 on it (#319)."""
    found = []
    for i, finding in enumerate(response.findings):
        level = finding.get("level")
        rule = finding.get("rule")
        ids = finding.get("ids")
        found.append(
            Finding(
                SIMULATION_FILE,
                level if level in ("error", "warning", "info") else "warning",
                "cheme.process-worker",
                f"{adapter.title} worker{f' ({rule})' if isinstance(rule, str) and rule else ''}: "
                + str(finding.get("message") or "finding without a message"),
                ids=[x for x in ids if isinstance(x, str)] if isinstance(ids, list) else [],
                hint=str(finding.get("hint") or f"Reported by the {adapter.title} worker."),
                key=f"worker-{i}",
            )
        )
    return found


def run(root, case, sim, *, write, save, adapter):
    from chemeascode.domains.process.model import load

    root = root.resolve()
    result = PropsResult()
    try:
        if save is not None:
            raise ValueError("--save is DWSIM-only")
        config = getattr(sim, adapter.configuration_name)
        process, findings = load(root)
        errors = [finding.message for finding in findings if finding.level == "error"]
        if errors:
            raise ValueError("Invalid process inputs: " + "; ".join(errors))
        if process is None or case not in {c.id for c in process.flowsheet.cases}:
            raise ValueError("Cannot load the requested flowsheet case")
        original = local_path(root, FLOWSHEET_FILE).read_bytes()
        run_file = local_path(root, record.RUN_FILE)
        previous = run_file.read_bytes() if run_file.exists() else None
        paths = worker_model.inputs(config)
        before = worker_model.hashes(root, config)
        source = source_revision(root, paths).as_dict()
        source["fingerprints"] = before.copy()
        current = worker_model.fingerprint(process, case, config, before, adapter)
        if current is None:
            raise ValueError(
                "Missing required model input: " + ", ".join(sorted(set(paths) - before.keys()))
            )
        if not write:
            from .run import _record_check

            result.findings.extend(_record_check(root, case, current))
        with tempfile.TemporaryDirectory(prefix="cheme-results-") as tmp:
            evidence = Path(tmp) / uuid4().hex
            evidence.mkdir()
            request = WorkerRequest(
                run_id=evidence.name,
                case=case,
                mode=config.mode,
                model=config.model,
                input=config.input,
                files=config.inputs,
                configuration=config.options,
                mappings=config.mappings,
                timeout_s=config.timeout_s,
                evidence=str(evidence),
                fingerprints={p: before[p] for p in config.inputs},
            )
            identities = _identities(process)
            _mappings(request, identities)
            execution = ExecutionOutcome(state="refused", transport="unselected")
            try:
                transport = adapter.transport(config)
                attempt = transport.execute(root, request)
                execution = attempt.execution
                if attempt.result is None:
                    raise ValueError(execution.message or "Worker returned no result")
                evidence_files(evidence)
                response = adapter.normalize(attempt.result, request, evidence)
                response.execution = execution
                result.findings.extend(_worker_findings(response, adapter))
                _map_results(response, request)
                (evidence / "cheme-adapter-result.json").write_text(
                    response.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
                )
                worker_evidence.validate(response, request, evidence, identities)
                content = worker_publication.filled(
                    original, case, response, config, current, adapter, set(process.components())
                )
                if worker_model.hashes(root, config) != before:
                    raise ValueError("Model inputs changed during execution")
                result.adapter = response
                result.lines.append(f"{adapter.title} {config.model}: {case}; {response.status}.")
                result.lines.extend(response.messages)
                (evidence / "cheme-worker-request.json").write_text(
                    request.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
                )
                if write:
                    source["fingerprints"][FLOWSHEET_FILE] = worker_model.raw_fingerprint(content)
                    entry = response.as_dict()
                    entry.update(
                        inputs=source,
                        model_fingerprint=current,
                        run_at=datetime.now(UTC).isoformat(),
                        converged=response.outcome.convergence == "converged",
                        integration_completed=bool(
                            response.outcome.integration and response.outcome.integration.completed
                        ),
                        producer=adapter.producer(config).model_dump(),
                        simulator=entry.pop("solver"),
                        property_package=None,
                        tool="cheme-as-code " + version("cheme-as-code"),
                    )
                    destination = worker_publication.publish(
                        root, case, entry, evidence, original, content, before, config, previous
                    )
                    result.lines.append(f"Evidence: {destination}")
                    if (destination / "report.html").is_file():
                        result.lines.append(f"Report: {destination / 'report.html'}")
                else:
                    result.lines.append("Check only: staged result discarded.")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                result.adapter = AdapterResult(
                    case=case,
                    status="refused" if execution.state == "refused" else "failed",
                    solver=Solver(name=adapter.title),
                    execution=execution,
                    messages=[str(exc)],
                )
                if write:
                    rejected = _failed_attempt(root, evidence, request, execution, str(exc))
                    result.lines.append(f"Rejected attempt: {rejected}")
                raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.findings.append(
            Finding(
                SIMULATION_FILE,
                "error",
                "cheme.process-worker",
                str(exc),
                hint="Review the adapter, execution environment and declared model inputs.",
            )
        )
    return result
