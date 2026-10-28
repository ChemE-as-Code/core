"""``cheme layout report``: what the generated model holds, line by line.

Per line number of the line list (and every line the P&IDs route): its routed and unrouted
segments with the reasons, its routed length, how it was routed and why (rack or local); the
router's counts per method and per reason (one per chain) and how the battery limit ends were
placed; the rack fill per tier; the model rule findings by rule; and how many objects are
generated, pinned or declared.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from chemeascode.foundation.findings import Finding


def layout_report(
    model: dict[str, Any], findings: list[Finding], line_numbers: list[str] | None = None
) -> dict[str, Any]:
    """The report as data (see the module text)."""
    lines: dict[str, dict[str, Any]] = {}
    for number in line_numbers or []:
        lines[number] = {"line": number, "routed": [], "unrouted": [], "length": 0.0}
    for pipe in model.get("pipes", []):
        entry = lines.setdefault(
            pipe["line"], {"line": pipe["line"], "routed": [], "unrouted": [], "length": 0.0}
        )
        entry["routed"].append(pipe["id"])
        entry["length"] += pipe.get("length", 0.0)
        entry.setdefault("methods", Counter())[pipe["method"]] += 1
        if pipe.get("reason"):
            entry.setdefault("reasons", Counter())[pipe["reason"]] += 1
    for item in model.get("unrouted", []):
        entry = lines.setdefault(
            item["line"], {"line": item["line"], "routed": [], "unrouted": [], "length": 0.0}
        )
        entry["unrouted"].append({"segment": item["segment"], "reason": item["reason"]})
    for entry in lines.values():
        entry["length"] = round(entry["length"], 1)
        entry["methods"] = dict(sorted(entry.get("methods", Counter()).items()))
        entry["reasons"] = dict(sorted(entry.get("reasons", Counter()).items()))
        if entry["unrouted"] and entry["routed"]:
            entry["status"] = "partly routed"
        elif entry["routed"]:
            entry["status"] = "routed"
        elif entry["unrouted"] and all(
            u["reason"].startswith("skipped") for u in entry["unrouted"]
        ):
            entry["status"] = "skipped"
        elif entry["unrouted"]:
            entry["status"] = "unrouted"
        else:
            entry["status"] = "not on a P&ID"
    sources: Counter[str] = Counter()
    for section in ("equipment", "structures", "platforms", "pipes", "inline", "zones"):
        for obj in model.get(section, []):
            sources[f"{section}:{obj.get('source', '?')}"] += 1
    rules = Counter(f.rule for f in findings)
    return {
        "lines": sorted(lines.values(), key=lambda e: e["line"]),
        "rack_fill": (model.get("routing") or {}).get("rack_fill", []),
        "methods": (model.get("routing") or {}).get("methods", {}),
        "reasons": (model.get("routing") or {}).get("reasons", {}),
        "battery_limits": (model.get("routing") or {}).get("battery_limits", {}),
        "findings": dict(sorted(rules.items())),
        "sources": dict(sorted(sources.items())),
        "review_needed": sorted(
            p["id"]
            for p in [*model.get("platforms", []), *model.get("pipes", [])]
            if p.get("review_needed")
        ),
    }


def format_report(report: dict[str, Any]) -> list[str]:
    """The report as text lines."""
    out = ["lines:"]
    for entry in report["lines"]:
        methods = ", ".join(f"{k} {v}" for k, v in entry["methods"].items())
        out.append(
            f"  {entry['line']}: {entry['status']}, {len(entry['routed'])} segments, "
            f"{entry['length']:g} m" + (f" ({methods})" if methods else "")
        )
        for item in entry["unrouted"]:
            out.append(f"    unrouted {item['segment']}: {item['reason']}")
    for title, key in (
        ("methods (chains)", "methods"),
        ("reasons (chains)", "reasons"),
        ("battery limit ends", "battery_limits"),
    ):
        if report.get(key):
            out.append(f"{title}:")
            out += [f"  {k}: {v}" for k, v in report[key].items()]
    out.append("rack fill:")
    for fill in report["rack_fill"]:
        out.append(
            f"  {fill['rack']} tier {fill['tier']:g} m: {fill['used_m']:.2f} of "
            f"{fill['width_m']:g} m ({fill['fill'] * 100:.0f} %)"
        )
    out.append(
        "findings: " + (", ".join(f"{k} {v}" for k, v in report["findings"].items()) or "none")
    )
    out.append("objects: " + ", ".join(f"{k} {v}" for k, v in report["sources"].items()))
    if report["review_needed"]:
        out.append(f"review needed (generated, not pinned): {len(report['review_needed'])}")
    return out
