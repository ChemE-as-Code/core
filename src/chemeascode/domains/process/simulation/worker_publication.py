"""Validate stream publication and replace the sheet/record with rollback on I/O failure.

Individual renames are atomic; the pair of files is not a filesystem transaction. The
exclusive writer lock, concurrent-input check and archived entry make that boundary explicit.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.fill import _child, _last_line
from chemeascode.domains.process.schema import CALCULATED_UNITS, Flowsheet
from chemeascode.domains.process.simulation import SOURCE, record, worker_model
from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.units import same_unit
from chemeascode.integrations.workers import evidence_files


def _flow(value):
    """*value* as a YAML flow node that reads back equal: JSON, except that a float in exponent
    form gets a decimal point (``1e-05`` -> ``1.0e-05``), since YAML 1.1 reads ``1e-05`` as a
    string (#316)."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_flow(k)}: {_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    text = json.dumps(value, ensure_ascii=False)
    if isinstance(value, float) and "e" in text and "." not in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}.0e{exponent}"
    return text


def _render_cells(content, case, document, measured=True):
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
            edits.append((start, end, _flow(after)))
            return
        key, *rest = keys
        pair = _child(node, key)
        if pair:
            patch(pair[1], rest, before[key], after[key])
        else:
            line = _last_line(node)
            end = offsets[line] + len(lines[line].rstrip("\r\n"))
            pad = " " * node.value[0][0].start_mark.column
            edits.append((end, end, newline + pad + _flow(key) + ": " + _flow(after[key])))

    for node, old, new in zip(nodes, original["streams"], document["streams"], strict=True):
        patch(node, ["state", case, *(["calculated"] if measured else [])], old, new)
    for start, end, snippet in sorted(edits, reverse=True):
        text = text[:start] + snippet + text[end:]
    if yaml.safe_load(text) != document:
        raise ValueError(
            "The new calculated fields cannot be written without changing other YAML values"
        )
    return text.encode("utf-8")


def filled(content, case, result, config, fingerprint, adapter, components):
    doc = yaml.safe_load(content)
    streams = {s["id"]: s for s in doc["streams"]}
    measured = adapter.publication == "measured"
    producer, legacy = adapter.producer(config), adapter.legacy_source(config)
    if not any(row.values for row in result.streams):
        raise ValueError("The worker returned no stream values")
    returned = {}
    for row in result.streams:
        if row.id not in streams or row.id in returned or row.filled:
            raise ValueError(f"Unexpected, duplicate or pre-filled worker stream {row.id}")
        returned[row.id] = row.values
        state = streams[row.id].setdefault("state", {}).setdefault(case, {})
        calculated = state.setdefault("calculated", {}) if measured else state
        for key, cell in row.values.items():
            if not measured and key not in {
                "temperature",
                "pressure",
                "flow",
                "duty",
                "composition",
            }:
                raise ValueError(f"Unsupported molecular state quantity {key}")
            if not measured and key == "composition":
                if (
                    not isinstance(cell, dict)
                    or set(cell) != {"values", "basis"}
                    or cell["basis"] not in {"mass_fraction", "mole_fraction"}
                    or not isinstance(cell["values"], dict)
                    or not cell["values"]
                    or not set(cell["values"]) <= components
                    or any(
                        type(v) not in (int, float) or not math.isfinite(v) or v < 0
                        for v in cell["values"].values()
                    )
                    or not math.isclose(sum(cell["values"].values()), 1, abs_tol=1e-8)
                ):
                    raise ValueError(f"Invalid molecular composition for {row.id}")
                payload = cell
            else:
                payload = _scalar(row.id, key, cell, measured, doc)
            old = calculated.get(key)
            if old is not None and not worker_model.owns(old, producer, legacy):
                raise ValueError(f"Protected calculated field {row.id}.{key} already exists")
            calculated[key] = {
                **payload,
                "provenance": "calculated",
                "origin": "simulated",
                "source": f"{SOURCE}: {adapter.title} {config.model}",
                "producer": producer.model_dump(),
                "fingerprint": fingerprint,
            }
            row.filled.append(key)
    # Remove obsolete outputs from this case; every other input and producer is preserved.
    for stream in streams.values():
        state = stream.get("state", {}).get(case, {})
        fields = state.get("calculated", {}) if measured else state
        current = returned.get(stream["id"], {})
        for key in list(fields):
            if (
                isinstance(fields[key], dict)
                and worker_model.owns(fields[key], producer, legacy)
                and key not in current
            ):
                del fields[key]
    Flowsheet.model_validate(doc)
    return _render_cells(content, case, doc, measured)


def _scalar(sid, key, cell, measured, doc):
    if not isinstance(cell, dict) or set(cell) != {"value", "unit"}:
        raise ValueError(f"{sid}.{key} requires a value and unit")
    value, unit = cell["value"], cell["unit"]
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not isinstance(unit, str)
        or not unit.strip()
    ):
        raise ValueError(f"Invalid measurement for {sid}.{key}")
    expected = (
        CALCULATED_UNITS.get(key) if measured else getattr(Flowsheet.model_validate(doc).units, key)
    )
    if expected and not same_unit(unit, expected):
        raise ValueError(f"Unexpected unit for {sid}.{key}: {unit}; expected {expected}")
    return cell


def _try_lock(fd):
    """Take an exclusive lock on *fd* without waiting (False: another process holds it). The
    operating system releases it when the process ends, however it ends."""
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def _publication_lock(lock):
    """Hold *lock* while publishing. A lock file left by a killed run holds no lock and is taken
    over; only a live publication refuses (#320)."""
    while True:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o644)
        try:
            if not _try_lock(fd):
                raise ValueError(
                    f"Another simulate --fill is publishing ({lock.name}); retry when it ends"
                )
            try:
                same = os.path.samestat(os.fstat(fd), os.stat(lock))
            except FileNotFoundError:
                same = False
        except BaseException:
            os.close(fd)
            raise
        if same:  # else the holder removed the file between our open and lock: open the new one
            break
        os.close(fd)
    try:
        yield
    finally:
        if os.name == "nt":  # an open file cannot be removed; another run may hold it by now
            os.close(fd)
            with contextlib.suppress(OSError):
                lock.unlink()
        else:
            with contextlib.suppress(FileNotFoundError):
                lock.unlink()
            os.close(fd)


def publish(root, case, entry, evidence, original, content, inputs_before, config, previous):
    for name in (FLOWSHEET_FILE, record.RUN_FILE, "process/simulation-runs"):
        if local_path(root, name) != root.resolve() / name:
            raise ValueError(f"Refusing a linked publication path: {name}")
    flowsheet = local_path(root, FLOWSHEET_FILE)
    run_file = local_path(root, record.RUN_FILE)
    evidence_root = local_path(root, "process/simulation-runs")
    evidence_root.mkdir(exist_ok=True)
    with _publication_lock(run_file.with_suffix(".lock")):
        if (
            worker_model.hashes(root, config) != inputs_before
            or flowsheet.read_bytes() != original
            or (run_file.read_bytes() if run_file.exists() else None) != previous
        ):
            raise ValueError("Model inputs changed during execution; retry with current inputs")
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
        encoded = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        with tempfile.TemporaryDirectory(dir=evidence_root) as temporary:
            temp = Path(temporary)
            (temp / "sheet").write_bytes(content)
            (temp / "previous-sheet").write_bytes(original)
            (temp / "record").write_bytes(encoded)
            shutil.copytree(evidence, temp / "evidence")
            evidence_files(temp / "evidence")
            (temp / "evidence" / "cheme-simulation-entry.json").write_text(
                json.dumps(entry, indent=2, allow_nan=False), encoding="utf-8"
            )
            os.replace(temp / "evidence", destination)
            try:
                os.replace(temp / "sheet", flowsheet)
                try:
                    os.replace(temp / "record", run_file)
                except OSError:
                    try:
                        os.replace(temp / "previous-sheet", flowsheet)
                    except OSError as rollback_error:
                        recovery = evidence_root / (evidence.name + "-recovery")
                        os.replace(temp, recovery)
                        raise ValueError(
                            "Publication and rollback failed; "
                            f"recover previous-sheet from {recovery}"
                        ) from rollback_error
                    raise
            except OSError:
                shutil.rmtree(destination)
                raise
        return destination
