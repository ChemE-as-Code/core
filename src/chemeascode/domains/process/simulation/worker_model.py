"""Inputs, ownership and fingerprints for a project-defined simulation model."""

from pathlib import Path

from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.simulation import SIMULATION_FILE, SOURCE
from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.provenance import file_fingerprint, value_fingerprint

VALUE_SOURCE = f"{SOURCE}: QSDsan "


def owns(value: dict) -> bool:
    return value.get("provenance") == "calculated" and (value.get("source") or "").startswith(
        VALUE_SOURCE
    )


def inputs(config) -> list[str]:
    return sorted({*config.inputs, SIMULATION_FILE, MATERIALS_FILE, FLOWSHEET_FILE})


def hashes(root: Path, config) -> dict[str, str]:
    return {
        name: file_fingerprint(path)
        for name in inputs(config)
        if (path := local_path(root, name)).is_file()
    }


def fingerprint(process, case, config, fingerprints):
    """Ignore only our derived cells so --fill cannot invalidate its own inputs."""
    if not set(inputs(config)) <= fingerprints.keys():
        return None
    flowsheet = process.flowsheet.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    for stream in flowsheet["streams"]:
        states = stream.get("state", {})
        for state in states.values():
            values = state.get("calculated", {})
            keep = {name: q for name, q in values.items() if not owns(q)}
            if keep:
                state["calculated"] = keep
            else:
                state.pop("calculated", None)
        if states:
            stream["state"] = {c: s for c, s in states.items() if s}
        if not stream.get("state"):
            stream.pop("state", None)
    files = {p: fingerprints[p] for p in inputs(config) if p != FLOWSHEET_FILE}
    return value_fingerprint({"contract": 1, "case": case, "flowsheet": flowsheet, "inputs": files})
