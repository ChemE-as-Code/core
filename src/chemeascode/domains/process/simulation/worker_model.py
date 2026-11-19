"""Inputs, ownership and fingerprints for a project-defined simulation model."""

import hashlib
from pathlib import Path

from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.simulation import SIMULATION_FILE
from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.provenance import value_fingerprint


def owns(value: dict, producer, legacy_source=None) -> bool:
    if value.get("provenance") != "calculated":
        return False
    recorded = value.get("producer")
    if recorded is not None:
        return (
            recorded.get("tool", "cheme process simulate") == producer.tool
            and recorded.get("adapter") == producer.adapter
            and recorded.get("model") == producer.model
        )
    return legacy_source is not None and value.get("source") == legacy_source


def is_worker_value(value: dict) -> bool:
    """Display includes structured producers and registered adapters' historical labels."""
    from .backends import BACKENDS

    if value.get("producer", {}).get("tool") == "cheme process simulate":
        return True
    from types import SimpleNamespace

    return any(
        prefix and (value.get("source") or "").startswith(prefix)
        for backend in BACKENDS.values()
        if backend.worker is not None
        for prefix in [backend.adapter.legacy_source(SimpleNamespace(model=""))]
    )


def raw_fingerprint(data: bytes) -> str:
    """Native simulator archives and text inputs are fingerprinted byte for byte."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def inputs(config) -> list[str]:
    return sorted({*config.inputs, SIMULATION_FILE, MATERIALS_FILE, FLOWSHEET_FILE})


def hashes(root: Path, config) -> dict[str, str]:
    return {
        name: raw_fingerprint(path.read_bytes())
        for name in inputs(config)
        if (path := local_path(root, name)).is_file()
    }


def fingerprint(process, case, config, fingerprints, adapter):
    """Ignore only our derived cells so --fill cannot invalidate its own inputs."""
    if not set(inputs(config)) <= fingerprints.keys():
        return None
    flowsheet = process.flowsheet.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    producer, legacy = adapter.producer(config), adapter.legacy_source(config)
    for stream in flowsheet["streams"]:
        states = stream.get("state", {})
        for state in states.values():
            values = state.get("calculated", {})
            keep = {name: q for name, q in values.items() if not owns(q, producer, legacy)}
            if keep:
                state["calculated"] = keep
            else:
                state.pop("calculated", None)
            for key in list(state):
                if isinstance(state[key], dict) and owns(state[key], producer, legacy):
                    del state[key]
        if states:
            stream["state"] = {c: s for c, s in states.items() if s}
        if not stream.get("state"):
            stream.pop("state", None)
    files = {p: fingerprints[p] for p in inputs(config) if p != FLOWSHEET_FILE}
    return value_fingerprint(
        {
            "contract": 2,
            "adapter": adapter.id,
            "case": case,
            "configuration": config.model_dump(mode="json"),
            "flowsheet": flowsheet,
            "inputs": files,
        }
    )
