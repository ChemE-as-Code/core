"""Run a trusted dynamic model and publish its results through the native process schema."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import yaml

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.fill import PropsResult, _child, _last_line
from chemeascode.domains.process.schema import CALCULATED_UNITS, Flowsheet
from chemeascode.domains.process.simulation import SIMULATION_FILE, record, worker_model
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.provenance import source_revision
from chemeascode.foundation.units import same_unit
from chemeascode.integrations import qsdsan


def _render_cells(content, case, document):
    """Patch native state mappings while retaining the authored YAML outside each edit."""
    text = content.decode("utf-8")
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    original = yaml.safe_load(text)
    nodes = _child(yaml.compose(text), "streams")[1].value
    edits = []

    def patch(node, keys, before, after):
        if before == after:
            return
        if node.flow_style or not keys:
            start = node.start_mark.index
            end = node.end_mark.index
            if not node.flow_style:
                end = offsets[_last_line(node)] + len(lines[_last_line(node)].rstrip("\r\n"))
            edits.append((start, end, json.dumps(after, ensure_ascii=False)))
            return
        key, *rest = keys
        pair = _child(node, key)
        if pair:
            patch(pair[1], rest, before[key], after[key])
        else:
            line = _last_line(node)
            end = offsets[line] + len(lines[line].rstrip("\r\n"))
            pad = " " * node.value[0][0].start_mark.column
            edits.append(
                (
                    end,
                    end,
                    newline
                    + pad
                    + json.dumps(key)
                    + ": "
                    + json.dumps(after[key], ensure_ascii=False),
                )
            )

    for node, old, new in zip(nodes, original["streams"], document["streams"], strict=True):
        patch(node, ["state", case, "calculated"], old, new)
    for start, end, snippet in sorted(edits, reverse=True):
        text = text[:start] + snippet + text[end:]
    if yaml.safe_load(text) != document:
        raise ValueError(
            "The new calculated fields cannot be written without changing other YAML values"
        )
    return text.encode("utf-8")


def _filled(content, case, adapter, config, fingerprint):
    doc = yaml.safe_load(content)
    streams = {s["id"]: s for s in doc["streams"]}
    if not any(row.values for row in adapter.streams):
        raise ValueError("The worker returned no stream values")
    returned = {}
    for row in adapter.streams:
        if row.id not in streams or row.id in returned or row.filled:
            raise ValueError(f"Unexpected, duplicate or pre-filled worker stream {row.id}")
        returned[row.id] = row.values
        state = streams[row.id].setdefault("state", {}).setdefault(case, {})
        calculated = state.setdefault("calculated", {})
        for key, cell in row.values.items():
            if not isinstance(cell, dict) or set(cell) != {"value", "unit"}:
                raise ValueError(f"{row.id}.{key} requires a value and unit")
            value, unit = cell["value"], cell["unit"]
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not isinstance(unit, str)
                or not unit.strip()
            ):
                raise ValueError(f"Invalid measurement for {row.id}.{key}")
            if key in CALCULATED_UNITS and not same_unit(unit, CALCULATED_UNITS[key]):
                raise ValueError(f"Unexpected unit for {row.id}.{key}: {unit}")
            old = calculated.get(key)
            if old is not None and not worker_model.owns(old):
                raise ValueError(f"Protected calculated field {row.id}.{key} already exists")
            calculated[key] = {
                "value": value,
                "unit": unit,
                "provenance": "calculated",
                "origin": "simulated",
                "source": worker_model.VALUE_SOURCE + config.model,
                "fingerprint": fingerprint,
            }
            row.filled.append(key)
    # Remove obsolete outputs from this case; every other input and producer is preserved.
    for stream in streams.values():
        fields = stream.get("state", {}).get(case, {}).get("calculated", {})
        current = returned.get(stream["id"], {})
        for key in list(fields):
            if worker_model.owns(fields[key]) and key not in current:
                del fields[key]
    Flowsheet.model_validate(doc)
    return _render_cells(content, case, doc)


def _publish(root, case, entry, evidence, original, content, inputs_before, config):
    for name in (FLOWSHEET_FILE, record.RUN_FILE, "process/simulation-runs"):
        if local_path(root, name) != root.resolve() / name:
            raise ValueError(f"Refusing a linked publication path: {name}")
    flowsheet = local_path(root, FLOWSHEET_FILE)
    run_file = local_path(root, record.RUN_FILE)
    evidence_root = local_path(root, "process/simulation-runs")
    evidence_root.mkdir(exist_ok=True)
    lock = run_file.with_suffix(".lock")
    with lock.open("x") as guard:
        try:
            if (
                worker_model.hashes(root, config) != inputs_before
                or flowsheet.read_bytes() != original
            ):
                raise ValueError("Model inputs changed during execution; retry with current inputs")
            previous = run_file.read_bytes() if run_file.exists() else None
            data = (
                record.parse(previous)
                if previous is not None
                else {"schema": record.RUN_SCHEMA, "kind": "simulation-run", "cases": {}}
            )
            if data is None:
                raise ValueError("Existing run record is unreadable; refusing to overwrite it")
            destination = evidence_root / evidence.name
            entry["evidence"] = destination.relative_to(root).as_posix()
            data["cases"][case] = entry
            encoded = (
                json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False).encode() + b"\n"
            )
            with tempfile.TemporaryDirectory(dir=evidence_root) as temporary:
                temp = Path(temporary)
                (temp / "sheet").write_bytes(content)
                (temp / "previous-sheet").write_bytes(original)
                (temp / "record").write_bytes(encoded)
                shutil.copytree(evidence, temp / "evidence")
                (temp / "evidence" / "cheme-simulation-entry.json").write_text(
                    json.dumps(entry, indent=2, allow_nan=False), encoding="utf-8"
                )
                os.replace(temp / "evidence", destination)
                try:
                    os.replace(temp / "sheet", flowsheet)
                    try:
                        os.replace(temp / "record", run_file)
                    except OSError:
                        os.replace(temp / "previous-sheet", flowsheet)
                        raise
                except OSError:
                    shutil.rmtree(destination)
                    raise
            return destination
        finally:
            guard.close()
            lock.unlink()


def run(root, case, sim, *, write, save):
    from chemeascode.domains.process.model import load

    result = PropsResult()
    try:
        if save is not None:
            raise ValueError("--save is DWSIM-only")
        config = sim.qsdsan
        process, findings = load(root)
        errors = [finding.message for finding in findings if finding.level == "error"]
        if errors:
            raise ValueError("Invalid process inputs: " + "; ".join(errors))
        if process is None or case not in {c.id for c in process.flowsheet.cases}:
            raise ValueError("Cannot load the requested flowsheet case")
        original = local_path(root, FLOWSHEET_FILE).read_bytes()
        paths = worker_model.inputs(config)
        before = worker_model.hashes(root, config)
        source = source_revision(root, paths).as_dict()
        current = worker_model.fingerprint(process, case, config, before)
        if current is None:
            raise ValueError(
                "Missing required model input: " + ", ".join(sorted(set(paths) - before.keys()))
            )
        if not write:
            from chemeascode.domains.process.simulation.run import _record_check

            result.findings.extend(_record_check(root, case, current))
        with tempfile.TemporaryDirectory(prefix="cheme-results-") as tmp:
            evidence = Path(tmp) / uuid4().hex
            evidence.mkdir()
            adapter = qsdsan.execute(root, config, case, evidence)
            if (
                adapter.case != case
                or adapter.solver.name != "QSDsan"
                or adapter.status != "converged"
                or any(f.get("level") == "error" for f in adapter.findings)
            ):
                raise ValueError("Worker returned a different case, solver or unsuccessful result")
            content = _filled(original, case, adapter, config, current)
            if worker_model.hashes(root, config) != before:
                raise ValueError("Model inputs changed during execution")
            result.adapter = adapter
            result.lines.append(f"QSDsan {config.model}: {case}; requested integration completed.")
            result.lines.extend(adapter.messages)
            if write:
                from chemeascode.foundation.provenance import content_fingerprint

                source["fingerprints"][FLOWSHEET_FILE] = content_fingerprint(content)
                entry = adapter.as_dict()
                entry.update(
                    inputs=source,
                    model_fingerprint=current,
                    run_at=datetime.now(UTC).isoformat(),
                    integration_completed=True,
                    converged=True,
                    simulator=entry.pop("solver"),
                    property_package=None,
                    tool="cheme-as-code " + version("cheme-as-code"),
                )
                destination = _publish(
                    root, case, entry, evidence, original, content, before, config
                )
                result.lines.append(f"Evidence: {destination}")
                if (destination / "report.html").is_file():
                    result.lines.append(f"Report: {destination / 'report.html'}")
            else:
                result.lines.append("Check only: staged result discarded.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.findings.append(
            Finding(
                SIMULATION_FILE,
                "error",
                "cheme.process-qsdsan",
                str(exc),
                hint="Review the worker configuration and declared inputs.",
            )
        )
    return result
