"""Process objects in ``cheme show`` and the process line of ``cheme status``."""

from __future__ import annotations

from typing import Any

from chemeascode.domains.process import FLOWSHEET_FILE


def _load(workspace: Any) -> Any:
    from chemeascode.domains.process.model import has_process, load

    if not has_process(workspace.root):
        return None
    return load(workspace.root)[0]


def show_lines(workspace: Any, key: str) -> list[str]:
    """What the flowsheet says about the block, step, feed, product or stream *key*."""
    process = _load(workspace)
    if process is None:
        return []
    fs = process.flowsheet
    stream = next((s for s in fs.streams if s.id == key), None)
    if stream is not None:
        shown = "shown on the BFD" if process.crossing(stream) else "internal (PFD only)"
        lines = [
            f"{FLOWSHEET_FILE}: stream {stream.id} {stream.title!r} ({stream.kind}), "
            f"{stream.from_} -> {stream.to}, {shown}"
        ]
        for case, state in stream.state.items():
            given = state.model_dump(exclude_none=True, exclude_defaults=True)
            lines.append(
                f"  {case}: "
                + ", ".join(
                    f"{name} {v.get('value', '')} {v.get('unit') or ''} [{v.get('provenance')}]"
                    for name, v in given.items()
                    if isinstance(v, dict) and "provenance" in v
                )
            )
        lines += [f"  link: {link.target} {link.ref}" for link in stream.links]
        return lines
    kind = process.kinds.get(key)
    if kind is None:
        return []
    node = process.nodes[key]
    lines = [
        f"{FLOWSHEET_FILE}: {kind} {key} {node.title!r}"
        + (f" in block {node.block}" if kind == "step" else "")
    ]
    if kind == "block":
        lines.append("  steps: " + (", ".join(s.id for s in process.steps_of(key)) or "none"))
    for port in node.ports:
        carried = [
            s.id for s in fs.streams if s.from_ == f"{key}.{port.id}" or s.to == f"{key}.{port.id}"
        ]
        extra = f", delegates {port.delegates}" if port.delegates else ""
        lines.append(
            f"  port {port.id} ({port.direction} {port.kind}{extra}): "
            + (", ".join(carried) or "no stream")
        )
    lines += [f"  link: {link.target} {link.ref}" for link in node.links]
    return lines


def status_summary(workspace: Any) -> dict[str, Any] | None:
    """Blocks, steps, streams and the balance state, or None without a flowsheet."""
    from chemeascode.domains.process.model import balances

    process = _load(workspace)
    if process is None:
        return None
    fs = process.flowsheet
    states: dict[str, int] = {}
    for result in balances(process):
        if result.kind == "block":
            states[result.status] = states.get(result.status, 0) + 1
    return {
        "blocks": len(fs.blocks),
        "steps": len(fs.steps),
        "streams": len(fs.streams),
        "case": fs.default_case(),
        "block_balances": states,
    }
