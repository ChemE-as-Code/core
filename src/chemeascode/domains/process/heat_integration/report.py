"""``cheme process pinch``: whole-plant pinch targets of a recorded simulation run.

The command reads the case's recorded run (``process/simulation-run.json``, written by ``cheme
process simulate --fill``); it never runs the simulator. The record must be current: the
inputs must still translate to the run's model fingerprint (as ``cheme process simulate
--check`` judges it), else the targets would describe another plant. The run's units and
stream temperatures are rebuilt into the simulator's result (:func:`.streams.out_from_record`),
its thermal streams extracted and reconciled (:func:`.streams.thermal_streams`), and the
targets taken by the problem table (:func:`.pinch.pinch_analysis`) at the given dTmin.

Three quantities, kept apart and labelled as such everywhere:

- **current utility demand**: the hot and cold utility the simulated plant uses, within the
  boundary of the targets (the streams that enter them: classes utility and recovery, and
  constrained with ``include_constrained``); recovered heat is not utility;
- **theoretical minimum utility demand at dTmin**: the pinch targets of the same streams;
- **theoretical energy-saving potential**: their difference. It ignores pressure, distance,
  fouling, control, safety and cost; it is not a saving and not a quantity of recoverable heat.

Utility-use pinch violations (a utility heater below the pinch, a utility cooler above it) are
reported apart from cross-pinch process-to-process transfer, which is evaluated only for the
existing exchangers whose sides are all known (both composites, counter-current, as
:func:`.pinch.minimum_approach` builds them). Together they explain the potential (the "more in,
more out" balance): ``potential = heater duty below the pinch + cooler duty above it +
cross-pinch transfer``, exactly for linearised streams; ``explained_kW`` says how far it holds.

Rules (``cheme.process-pinch-*``, file ``process/simulation-run.json``):

- ``pinch-sim-missing`` (error): no ``process/simulation.yaml``, or the case's model does not
  translate;
- ``pinch-run-missing`` (error), ``pinch-run-stale`` (error), ``pinch-run-not-converged``
  (error): no current converged run of the case is recorded;
- ``pinch-reconciliation`` (warning): a duty of the run the extracted streams do not give back
  within its tolerance; ``--write`` refuses;
- ``pinch-no-targets`` (error): fewer than two streams enter the targets;
- ``pinch-stream-linearised`` (info): the streams that enter the targets linearised (all, today);
- ``pinch-stream-excluded`` (info), ``pinch-stream-constrained`` (info): a duty left out of the
  targets, with its reason;
- ``pinch-below-target`` (info): the current utility is below the target at this dTmin (an
  existing exchanger approaches closer than dTmin).

``process/pinch-run.json`` (schema ``cheme/pinch-run/v1``, :func:`write`) keeps one entry per
case: the settings (dTmin with its source, or ``ASSUMED``; the engine; constrained streams
included or not), the core version, the simulation run it rests on (model fingerprint and the
entry's content fingerprint), the inputs' fingerprints and the results. It is generated; never
edit it by hand.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.domains.process.heat_integration.pinch import (
    TARGETS_SCOPE,
    PinchResult,
    PinchStream,
    _composite,
    minimum_approach,
    pinch_analysis,
)
from chemeascode.domains.process.heat_integration.streams import (
    Extraction,
    ThermalStream,
    duty_tolerance,
    out_from_record,
    thermal_streams,
)
from chemeascode.foundation.findings import Finding

PINCH_FILE = "process/pinch-run.json"
PINCH_SCHEMA = "cheme/pinch-run/v1"
#: The engine: core's problem table (the only one today).
ENGINE = "native"
#: What the three quantities are, in the words every output uses.
LABELS = {
    "current": "current utility demand",
    "minimum": "theoretical minimum utility demand at dTmin",
    "potential": "theoretical energy-saving potential",
}
POTENTIAL_NOTE = (
    "the difference between the current and the theoretical minimum utility demand of the same "
    "streams; it ignores pressure, distance, fouling, control, safety and cost, and is neither a "
    "saving nor a quantity of recoverable heat"
)
#: Temperatures this close to the pinch are at it, K.
AT_PINCH = 1e-9


class UnknownCase(ValueError):
    """The case is not one of the flowsheet's."""


def _finding(
    level: str, rule: str, message: str, ids: list[str], hint: str, key: str = ""
) -> Finding:
    from chemeascode.domains.process.simulation.record import RUN_FILE

    return Finding(
        RUN_FILE,
        level,  # type: ignore[arg-type]
        f"cheme.process-pinch-{rule}",
        message,
        ids=ids,
        hint=hint,
        key=key,
    )


@dataclass
class PinchReport:
    """The targets of one case, or the findings why there are none."""

    case: str
    dt_min: float
    dt_min_source: str
    include_constrained: bool
    extraction: Extraction | None = None
    result: PinchResult | None = None
    current: dict[str, float] = field(default_factory=dict)
    minimum: dict[str, float] = field(default_factory=dict)
    potential: dict[str, float] = field(default_factory=dict)
    violations: list[dict[str, Any]] = field(default_factory=list)
    cross_pinch: list[dict[str, Any]] = field(default_factory=list)
    explained_kW: float | None = None
    simulation: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(f.level == "error" for f in self.findings)

    @property
    def unreconciled(self) -> bool:
        return self.extraction is not None and not self.extraction.reconciliation.closed

    def settings(self) -> dict[str, Any]:
        return {
            "engine": ENGINE,
            "dt_min": {"value": self.dt_min, "unit": "K", "source": self.dt_min_source},
            "include_constrained": self.include_constrained,
        }

    def results(self) -> dict[str, Any]:
        """Everything the command computed (JSON-ready)."""
        from chemeascode.foundation.schemas.run import finding_dict

        r = self.result
        ex = self.extraction
        return {
            "labels": dict(LABELS),
            "current_utility_demand_kW": self.current or None,
            "minimum_utility_demand_kW": self.minimum or None,
            "energy_saving_potential_kW": self.potential or None,
            "potential_note": POTENTIAL_NOTE,
            "boundary": "the streams that enter the targets: classes utility and recovery"
            + (", and constrained (sensitivity)" if self.include_constrained else "")
            + "; the other duties are listed with their reasons, not targeted",
            "pinch": None
            if r is None
            else {
                "threshold": r.threshold,
                "shifted_K": r.pinch_shifted_temperature,
                "hot_side_K": r.pinch_hot_temperature,
                "cold_side_K": r.pinch_cold_temperature,
            },
            "basis": None if r is None else r.basis,
            "scope": TARGETS_SCOPE,
            "stream_basis": None if ex is None else ex.basis,
            "grand_composite_curve": None
            if r is None
            else [{"shifted_K": t, "kW": q} for t, q in r.grand_composite_curve],
            "utility_pinch_violations": self.violations,
            "cross_pinch_transfer": self.cross_pinch,
            "explained_kW": self.explained_kW,
            "shares": None if ex is None else ex.shares(),
            "streams": [] if ex is None else [s.entry() for s in ex.streams],
            "reconciliation": None if ex is None else ex.reconciliation.entry(),
            "findings": [finding_dict(f) for f in self.findings],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "settings": self.settings(),
            "simulation_run": self.simulation or None,
            **self.results(),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)


# -- the report --------------------------------------------------------------------------------


def pinch_report(
    root: Path,
    process: Any,
    case: str | None,
    dt_min: float,
    *,
    dt_min_source: str = "ASSUMED",
    include_constrained: bool = False,
) -> PinchReport:
    """The targets of *case* (default: the default case) at *dt_min* K from its recorded,
    current simulation run. Raises :class:`UnknownCase` and ``ValueError`` for a negative
    *dt_min*."""
    from chemeascode.domains.process.simulation import record
    from chemeascode.domains.process.simulation.translate import load, translate
    from chemeascode.foundation.provenance import content_fingerprint

    if dt_min < 0:
        raise ValueError("--dt-min must not be negative")
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        raise UnknownCase(f"unknown case {case!r}")
    report = PinchReport(case, dt_min, dt_min_source or "ASSUMED", include_constrained)
    sim, sim_doc, found = load(Path(root))
    if sim is None:
        report.findings += found
        report.findings.append(
            _finding(
                "error",
                "sim-missing",
                "no simulation to take the streams from (process/simulation.yaml does not load)",
                [case],
                "write process/simulation.yaml and run cheme process simulate --fill",
            )
        )
        return report
    translation = translate(process, sim, sim_doc, case)
    if translation.model is None:
        report.findings += [f for f in translation.findings if f.level == "error"]
        report.findings.append(
            _finding(
                "error",
                "sim-missing",
                f"case {case}: the simulator model does not translate, so no run can be current",
                [case],
                "fix the errors above (cheme process simulate --check)",
            )
        )
        return report
    entry = record.entry_of(record.read(Path(root)), case)
    if entry is None:
        report.findings.append(
            _finding(
                "error",
                "run-missing",
                f"case {case}: no run recorded in {record.RUN_FILE}",
                [case],
                "run cheme process simulate --fill (it records the run); pinch never runs the "
                "simulator itself",
            )
        )
        return report
    report.simulation = {
        "file": record.RUN_FILE,
        "case": case,
        "run_at": entry.get("run_at"),
        "tool": entry.get("tool"),
        "simulator": entry.get("simulator"),
        "model_fingerprint": entry.get("model_fingerprint"),
        "entry_fingerprint": content_fingerprint(
            json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
        ),
    }
    if entry.get("model_fingerprint") != translation.fingerprint:
        report.findings.append(
            _finding(
                "error",
                "run-stale",
                f"case {case}: the recorded run was simulated from other inputs (feeds, specs, "
                "property package or simulator model changed); its duties are not this plant's",
                [case],
                "run cheme process simulate --fill, then cheme process pinch again",
            )
        )
        return report
    if not entry.get("converged"):
        report.findings.append(
            _finding(
                "error",
                "run-not-converged",
                f"case {case}: the recorded run did not converge",
                [case],
                "make the simulation converge (cheme process simulate --fill)",
            )
        )
        return report
    out = out_from_record(entry, translation.model)
    extraction = thermal_streams(translation.model, out, case, process=process)
    report.extraction = extraction
    report.findings += _stream_findings(extraction, include_constrained)
    targeted = extraction.targeted(include_constrained)
    if len(targeted) < 2:
        report.findings.append(
            _finding(
                "error",
                "no-targets",
                f"case {case}: {len(targeted)} stream(s) with thermal data enter the targets; "
                "the problem table needs at least 2",
                [case],
                "check the excluded duties and their reasons",
            )
        )
        return report
    _targets(report, targeted)
    return report


def _stream_findings(extraction: Extraction, include_constrained: bool) -> list[Finding]:
    findings: list[Finding] = []
    targeted = extraction.targeted(include_constrained)
    linear = [s for s in targeted if s.quality == "linearised"]
    if linear:
        findings.append(
            _finding(
                "info",
                "stream-linearised",
                f"{len(linear)} of {len(targeted)} streams in the targets are linearised (one "
                "constant-CP or isothermal segment between inlet and outlet temperature; "
                f"{sum(s.duty_kW for s in linear):.6g} kW): the simulation reports no "
                "enthalpy-temperature profile, so the targets rest on linearised streams",
                sorted({s.unit for s in linear}),
                "where a stream changes phase or its heat capacity varies strongly, check its "
                "profile in the simulator before relying on the pinch temperature",
            )
        )
    for s in extraction.streams:
        if s.category == "excluded":
            findings.append(
                _finding(
                    "info",
                    "stream-excluded",
                    f"{s.id} ({s.unit_type}, {s.role}): {s.duty_kW:.6g} kW left out of the "
                    f"targets: {s.reason}",
                    [s.unit],
                    "give the missing data, or account for the duty in the review",
                    key=s.id,
                )
            )
        elif s.category == "constrained":
            findings.append(
                _finding(
                    "info",
                    "stream-constrained",
                    f"{s.id} ({s.unit_type}): {s.duty_kW:.6g} kW constrained ("
                    + ("included as a sensitivity" if include_constrained else "not in the targets")
                    + f"): {s.reason}",
                    [s.unit],
                    "--include-constrained shows the targets with it",
                    key=s.id,
                )
            )
    for row in extraction.reconciliation.leftover:
        findings.append(
            _finding(
                "warning",
                "reconciliation",
                f"{row['unit']} ({row['role']}): {row['kW']:.6g} kW of the run not given back by "
                f"the extracted streams (residual {row['residual_kW']:.6g} kW): {row['reason']}",
                [row["unit"]],
                "the targets miss heat of the run: report it as an open item; --write refuses",
                key=f"{row['unit']}:{row['role']}",
            )
        )
    return findings


def _targets(report: PinchReport, targeted: list[ThermalStream]) -> None:
    streams = [s.pinch_stream() for s in targeted]
    result = pinch_analysis(streams, report.dt_min)
    report.result = result
    hot_now = sum(s.duty_kW for s in targeted if s.category != "recovery" and s.side == "cold")
    cold_now = sum(s.duty_kW for s in targeted if s.category != "recovery" and s.side == "hot")
    report.current = {"hot_kW": hot_now, "cold_kW": cold_now}
    report.minimum = {"hot_kW": result.min_hot_utility, "cold_kW": result.min_cold_utility}
    report.potential = {
        "hot_kW": hot_now - result.min_hot_utility,
        "cold_kW": cold_now - result.min_cold_utility,
    }
    tol = duty_tolerance(max(hot_now, cold_now))
    if min(report.potential.values()) < -tol:
        report.findings.append(
            _finding(
                "info",
                "below-target",
                f"the current utility demand is below the theoretical minimum at dTmin "
                f"{report.dt_min:g} K (hot {report.potential['hot_kW']:.6g} kW): an existing "
                "exchanger approaches closer than dTmin",
                [report.case],
                "compare the exchangers' approaches (cheme process energy) with dTmin",
            )
        )
    if result.threshold:
        report.explained_kW = None
        return
    t_hot, t_cold = result.pinch_hot_temperature, result.pinch_cold_temperature
    assert t_hot is not None and t_cold is not None
    for s in targeted:
        if s.category == "recovery":
            continue
        kw = _below(s, t_cold) if s.side == "cold" else _above(s, t_hot)
        if kw > AT_PINCH:
            report.violations.append(
                {
                    "stream": s.id,
                    "unit": s.unit,
                    "role": s.role,
                    "class": s.category,
                    "utility": s.utility,
                    "kind": "heater below the pinch"
                    if s.side == "cold"
                    else "cooler above the pinch",
                    "kW": kw,
                    "of_kW": s.duty_kW,
                }
            )
    groups: dict[str, list[ThermalStream]] = {}
    for s in targeted:
        if s.category == "recovery" and s.exchange:
            groups.setdefault(s.exchange, []).append(s)
    for exchange, sides in groups.items():
        hot = [s.pinch_stream() for s in sides if s.side == "hot"]
        cold = [s.pinch_stream() for s in sides if s.side == "cold"]
        if not hot or not cold:
            continue
        forward, reverse = _cross(hot, cold, t_hot, t_cold)
        approach = minimum_approach([*hot, *cold])
        report.cross_pinch.append(
            {
                "exchange": exchange,
                "hot": [s.id for s in sides if s.side == "hot"],
                "cold": [s.id for s in sides if s.side == "cold"],
                "kW": forward - reverse,
                "hot_above_to_cold_below_kW": forward,
                "hot_below_to_cold_above_kW": reverse,
                "minimum_approach_K": approach.minimum,
            }
        )
    report.explained_kW = sum(v["kW"] for v in report.violations) + sum(
        c["kW"] for c in report.cross_pinch
    )


def _below(s: ThermalStream, t: float) -> float:
    """kW of a cold stream's duty taken below *t* K."""
    kw = 0.0
    for seg in s.segments:
        lo = min(seg.supply_temperature, seg.target_temperature)
        hi = max(seg.supply_temperature, seg.target_temperature)
        if seg.isothermal:
            kw += seg.duty if lo < t - AT_PINCH else 0.0
        else:
            kw += seg.duty * max(0.0, min(hi, t) - lo) / (hi - lo)
    return kw


def _above(s: ThermalStream, t: float) -> float:
    """kW of a hot stream's duty given above *t* K."""
    kw = 0.0
    for seg in s.segments:
        lo = min(seg.supply_temperature, seg.target_temperature)
        hi = max(seg.supply_temperature, seg.target_temperature)
        if seg.isothermal:
            kw += seg.duty if lo > t + AT_PINCH else 0.0
        else:
            kw += seg.duty * max(0.0, hi - max(lo, t)) / (hi - lo)
    return kw


def _first_at_or_above(points: list[tuple[float, float]], t: float) -> float:
    """The least heat where the composite *points* (heat, T ascending) reach *t*; inf if never."""
    for (h0, t0), (h1, t1) in zip(points, points[1:], strict=False):
        if t0 >= t:
            return h0
        if t1 >= t:
            return h0 if t1 == t0 else h0 + (t - t0) / (t1 - t0) * (h1 - h0)
    return points[0][0] if points and points[0][1] >= t else float("inf")


def _last_at_or_below(points: list[tuple[float, float]], t: float) -> float:
    """The greatest heat where the composite *points* are at or below *t*; -inf if never."""
    pairs = list(zip(points, points[1:], strict=False))
    for (h0, t0), (h1, t1) in reversed(pairs):
        if t1 <= t:
            return h1
        if t0 <= t:
            return h1 if t1 == t0 else h0 + (t - t0) / (t1 - t0) * (h1 - h0)
    return points[-1][0] if points and points[-1][1] <= t else float("-inf")


def _cross(
    hot: list[PinchStream], cold: list[PinchStream], t_hot: float, t_cold: float
) -> tuple[float, float]:
    """(kW from hot above *t_hot* to cold below *t_cold*, kW from hot below to cold above) in
    one counter-current exchange of *hot* and *cold* (composites from their cold ends)."""
    h, c = _composite(hot), _composite(cold)
    top = min(h[-1][0], c[-1][0])

    def clip(q: float) -> float:
        return min(max(q, 0.0), top)

    # hot above its pinch: heat (qh, top]; cold below its pinch: [0, qc)
    forward = max(0.0, clip(_first_at_or_above(c, t_cold)) - clip(_last_at_or_below(h, t_hot)))
    # hot below: [0, qh'); cold above: (qc', top]
    reverse = max(0.0, clip(_first_at_or_above(h, t_hot)) - clip(_last_at_or_below(c, t_cold)))
    return forward, reverse


# -- output ------------------------------------------------------------------------------------


def _kw(v: float | None) -> str:
    return "-" if v is None else f"{v:.6g}"


def _k(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f} K"


def _summary(report: PinchReport) -> list[str]:
    r = report.result
    lines = [
        f"Pinch targets, case {report.case}: dTmin {report.dt_min:g} K ({report.dt_min_source}), "
        f"engine {ENGINE}, constrained "
        + ("included (sensitivity)" if report.include_constrained else "excluded")
    ]
    if report.simulation:
        sim = report.simulation
        lines.append(
            f"from {sim['file']} (run {sim.get('run_at')}, {sim.get('tool')}, model "
            f"{sim.get('model_fingerprint')})"
        )
    if r is None:
        return lines
    lines += [
        f"{LABELS['current']}: hot {_kw(report.current['hot_kW'])} kW, cold "
        f"{_kw(report.current['cold_kW'])} kW",
        f"{LABELS['minimum']} {report.dt_min:g} K: hot {_kw(report.minimum['hot_kW'])} kW, cold "
        f"{_kw(report.minimum['cold_kW'])} kW",
        f"{LABELS['potential']}: hot {_kw(report.potential['hot_kW'])} kW, cold "
        f"{_kw(report.potential['cold_kW'])} kW ({POTENTIAL_NOTE})",
    ]
    if r.threshold:
        lines.append(
            "threshold problem: no pinch (one utility target is zero); no utility-use pinch "
            "violations or cross-pinch transfer are defined"
        )
    else:
        lines.append(
            f"pinch: hot side {_k(r.pinch_hot_temperature)}, cold side "
            f"{_k(r.pinch_cold_temperature)}, shifted {_k(r.pinch_shifted_temperature)}"
        )
    return lines


def pinch_text(report: PinchReport) -> str:
    """The report as ``cheme process pinch`` prints it."""
    lines = _summary(report)
    ex = report.extraction
    if report.result is not None and not report.result.threshold:
        lines.append("utility-use pinch violations:" + ("" if report.violations else " none"))
        for v in report.violations:
            lines.append(
                f"  {v['stream']}: {v['kind']}, {_kw(v['kW'])} of {_kw(v['of_kW'])} kW"
                + (f" ({v['utility']})" if v["utility"] else "")
                + (" [constrained]" if v["class"] == "constrained" else "")
            )
        lines.append(
            "cross-pinch process-to-process transfer (existing exchangers, both sides known):"
            + ("" if report.cross_pinch else " none")
        )
        for c in report.cross_pinch:
            lines.append(
                f"  {c['exchange']}: {_kw(c['kW'])} kW (hot {', '.join(c['hot'])}, cold "
                f"{', '.join(c['cold'])}; least approach {c['minimum_approach_K']:.3g} K)"
            )
        if report.explained_kW is not None:
            lines.append(
                f"  violations plus cross-pinch transfer: {_kw(report.explained_kW)} kW of the "
                f"potential {_kw(report.potential['hot_kW'])} kW"
            )
    if ex is not None:
        lines.append("streams (kW, K):")
        for s in ex.streams:
            lines.append(
                f"  {s.id}: {s.category}, {s.quality}, {s.side or '-'}, {_kw(s.duty_kW)} kW, "
                f"{_k(s.supply_K)} -> {_k(s.target_K)}"
                + (f", {s.utility}" if s.utility else "")
                + (
                    f"; {s.reason}"
                    if s.reason and s.category in ("excluded", "constrained")
                    else ""
                )
            )
        shares = ex.shares()
        lines.append(
            "shares of the run's thermal duty: class "
            + ", ".join(f"{k} {v:.1%}" for k, v in shares["class"].items())
            + "; quality "
            + ", ".join(f"{k} {v:.1%}" for k, v in shares["quality"].items())
        )
        rec = ex.reconciliation
        lines.append(
            f"reconciliation: {'closed' if rec.closed else 'NOT closed'}; run duties "
            f"{_kw(rec.total_kW)} kW = "
            + " + ".join(f"{k} {_kw(v)}" for k, v in rec.by_class.items())
            + f" + left over {_kw(rec.residual_kW)}"
        )
    for f in report.findings:
        lines.append(f.format())
    return "\n".join(lines)


def pinch_markdown(report: PinchReport) -> str:
    """The report as Markdown (``--md``)."""
    lines = [f"## Pinch targets, case {report.case}", ""]
    r = report.result
    lines.append(
        f"dTmin {report.dt_min:g} K ({report.dt_min_source}); engine {ENGINE}; constrained "
        + ("included (sensitivity)" if report.include_constrained else "excluded")
        + "."
    )
    if report.simulation:
        sim = report.simulation
        lines.append(
            f"From `{sim['file']}`, run {sim.get('run_at')} ({sim.get('tool')}), model "
            f"`{sim.get('model_fingerprint')}`."
        )
    lines.append("")
    if r is not None:
        lines += [
            "| quantity | hot kW | cold kW |",
            "|---|---|---|",
            f"| {LABELS['current']} | {_kw(report.current['hot_kW'])} | "
            f"{_kw(report.current['cold_kW'])} |",
            f"| {LABELS['minimum']} {report.dt_min:g} K | {_kw(report.minimum['hot_kW'])} | "
            f"{_kw(report.minimum['cold_kW'])} |",
            f"| {LABELS['potential']} | {_kw(report.potential['hot_kW'])} | "
            f"{_kw(report.potential['cold_kW'])} |",
            "",
            f"The {LABELS['potential']} is {POTENTIAL_NOTE}.",
            "",
        ]
        if r.threshold:
            lines.append("Threshold problem: no pinch.")
        else:
            lines.append(
                f"Pinch: hot side {_k(r.pinch_hot_temperature)}, cold side "
                f"{_k(r.pinch_cold_temperature)}, shifted {_k(r.pinch_shifted_temperature)}."
            )
            lines += ["", "Utility-use pinch violations:", ""]
            if report.violations:
                lines += ["| stream | kind | kW | of kW | utility |", "|---|---|---|---|---|"]
                lines += [
                    f"| {v['stream']} | {v['kind']} | {_kw(v['kW'])} | {_kw(v['of_kW'])} | "
                    f"{v['utility'] or '-'} |"
                    for v in report.violations
                ]
            else:
                lines.append("None.")
            lines += ["", "Cross-pinch process-to-process transfer (existing exchangers):", ""]
            if report.cross_pinch:
                lines += ["| exchange | kW | least approach K |", "|---|---|---|"]
                lines += [
                    f"| {c['exchange']} | {_kw(c['kW'])} | {c['minimum_approach_K']:.3g} |"
                    for c in report.cross_pinch
                ]
            else:
                lines.append("None.")
        lines.append("")
    ex = report.extraction
    if ex is not None:
        lines += [
            "| stream | unit | role | class | quality | side | kW | supply K | target K | "
            "utility | reason |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in ex.streams:
            lines.append(
                f"| {s.id} | {s.unit} | {s.role} | {s.category} | {s.quality} | {s.side or '-'} "
                f"| {_kw(s.duty_kW)} | {_kw(s.supply_K)} | {_kw(s.target_K)} | "
                f"{s.utility or '-'} | {s.reason or '-'} |"
            )
        rec = ex.reconciliation
        lines += [
            "",
            f"Reconciliation: {'closed' if rec.closed else 'not closed'}; run duties "
            f"{_kw(rec.total_kW)} kW = "
            + " + ".join(f"{k} {_kw(v)}" for k, v in rec.by_class.items())
            + f" + left over {_kw(rec.residual_kW)} kW.",
        ]
    if report.findings:
        lines += ["", "Findings:", ""]
        lines += [f"- `{f.format()}`" for f in report.findings]
    return "\n".join(lines)


# -- the record --------------------------------------------------------------------------------


def read(root: Path) -> dict[str, Any] | None:
    path = Path(root) / PINCH_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != PINCH_SCHEMA:
        return None
    return data


def make_entry(root: Path, report: PinchReport) -> dict[str, Any]:
    """The record entry of *report* (see the module docstring)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.simulation import SIMULATION_FILE
    from chemeascode.domains.process.simulation.record import RUN_FILE
    from chemeascode.foundation.provenance import source_revision
    from chemeascode.foundation.workspace import installed_version

    now = _dt.datetime.now(_dt.UTC).replace(microsecond=0)
    return {
        "case": report.case,
        "run_at": now.isoformat().replace("+00:00", "Z"),
        "tool": "cheme-as-code " + ".".join(str(n) for n in installed_version()),
        "settings": report.settings(),
        "simulation_run": report.simulation,
        "inputs": source_revision(
            Path(root), (RUN_FILE, FLOWSHEET_FILE, SIMULATION_FILE)
        ).as_dict(),
        "results": report.results(),
    }


def write(root: Path, report: PinchReport) -> dict[str, Any]:
    """Store *report* as its case's entry of ``process/pinch-run.json``, keeping the other
    cases. Raises ``ValueError`` for a report with an error or an open reconciliation (the CLI
    refuses before)."""
    if report.failed or report.result is None:
        raise ValueError("no targets to record")
    if report.unreconciled:
        raise ValueError("the reconciliation has a finding: not recorded")
    entry = make_entry(root, report)
    data = read(root) or {"schema": PINCH_SCHEMA, "kind": "pinch-run", "cases": {}}
    data["cases"][report.case] = entry
    data["cases"] = dict(sorted(data["cases"].items()))
    path = Path(root) / PINCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry
