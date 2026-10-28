"""Energy balances of the flowsheet: stream enthalpies against energy streams, per block and step.

The mass, component and element balances (:func:`chemeascode.domains.process.model.balances`)
have an energy counterpart here. For a block or step in one case, the material streams crossing
its boundary carry ``enthalpy`` (``state.calculated.enthalpy``, kJ/kmol on
``units.enthalpy_reference``) times their molar flow, and the energy streams crossing it carry
their ``duty`` (in when it ends inside). The balance closes when enthalpy out minus enthalpy in
equals energy in minus energy out within :data:`ENERGY_TOLERANCE`.

What is not evaluated is said, never estimated:

- ``not-evaluable``: a crossing material stream lacks its enthalpy, flow or molar mass, or an
  energy stream its duty; an enthalpy not in kJ/kmol or a molar mass not in kg/kmol counts as
  missing (and is ``cheme.process-unit``): it is never read in another unit;
- ``unsupported``: the enthalpies cannot be compared on one basis. A reacting block or step
  (``reactions:`` or ``balance_scope: reactive``) needs a heat-of-formation basis
  (``units.enthalpy_reference.state: elements``); thermo's values from ``cheme process props``
  are on :data:`chemeascode.domains.process.props.ENTHALPY_REFERENCE` (ideal gas, without
  formation enthalpies), so they are unsupported there, as is any value calculated by props
  while the flowsheet declares another reference; ``balance_scope: dynamic`` is not balanced;
- ``no-energy-streams``: no energy stream crosses the boundary; the enthalpy difference is
  reported as the implied duty (``residual_kW``), not as an imbalance: whether the node is
  adiabatic or its duty is undeclared is the boundary-completeness check's question
  (:func:`chemeascode.domains.assessment.flows.boundary_gaps`).

Rules (``cheme.process-*``, from :func:`chemeascode.domains.process.model.rules`):
``energy-balance`` (warning) where a balance with energy streams does not close,
``energy-balance-unsupported`` (info) where every value is there but the reference does not
allow the balance.

:func:`energy_report` puts these together with the energy audit of the last simulation run
(``process/simulation-run.json``, :mod:`chemeascode.domains.process.simulation.energy`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.model import Process, stream_flows
from chemeascode.domains.process.schema import CALCULATED_UNITS, DUTY_UNITS, Block
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.yamlsource import _yaml_line

#: ``|residual| <= abs_kW + rel_duty * (|Q| + |W|) + rel_enthalpy * max(sum |H in|, sum |H out|)``
#: (kW); the enthalpy term allows for rounding of large absolute enthalpy flows, which depend on
#: the reference state. Shared with the simulation's energy audit.
ENERGY_TOLERANCE = {"abs_kW": 0.1, "rel_duty": 0.01, "rel_enthalpy": 1e-4}
#: Source prefix of the enthalpies ``cheme process props`` writes (thermo).
PROPS_SOURCE = "cheme process props"


def tolerance(energy: float, h_in: float, h_out: float) -> float:
    """The closure tolerance, kW, for *energy* kW exchanged (heat and work, magnitudes) and the
    magnitudes of the enthalpy flows in and out."""
    t = ENERGY_TOLERANCE
    return t["abs_kW"] + t["rel_duty"] * energy + t["rel_enthalpy"] * max(h_in, h_out)


@dataclass
class EnergyBalance:
    """The energy balance of one block or step in one case (kW)."""

    node: str
    kind: str  # block or step
    status: str  # ok, imbalance, not-evaluable, unsupported, no-energy-streams, no-streams
    enthalpy_in: float = 0.0
    enthalpy_out: float = 0.0
    energy_in: float = 0.0
    energy_out: float = 0.0
    residual: float | None = None
    tolerance: float | None = None
    missing: list[str] = field(default_factory=list)
    reason: str = ""
    energy_streams: list[str] = field(default_factory=list)

    def entry(self) -> dict[str, Any]:
        out = {
            "node": self.node,
            "kind": self.kind,
            "status": self.status,
            "enthalpy_in_kW": round(self.enthalpy_in, 6),
            "enthalpy_out_kW": round(self.enthalpy_out, 6),
            "energy_in_kW": round(self.energy_in, 6),
            "energy_out_kW": round(self.energy_out, 6),
            "residual_kW": None if self.residual is None else round(self.residual, 6),
            "tolerance_kW": None if self.tolerance is None else round(self.tolerance, 6),
            "missing": self.missing,
            "energy_streams": self.energy_streams,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


def _reference_problem(process: Process, enthalpies: list[Any], node: str) -> str:
    """Why the enthalpies of *node*'s streams cannot be balanced on one basis, or ''."""
    from chemeascode.domains.process.props import ENTHALPY_REFERENCE

    ref = process.flowsheet.units.enthalpy_reference
    if ref is None:
        return "units.enthalpy_reference is not given"
    by_props = [q for q in enthalpies if (q.source or "").startswith(PROPS_SOURCE)]
    declared = {"state": ref.state, "temperature": ref.temperature}
    thermo = {k: ENTHALPY_REFERENCE[k] for k in ("state", "temperature")}
    if by_props and (
        declared["state"] != thermo["state"]
        or abs(declared["temperature"] - thermo["temperature"]) > 1e-6
    ):
        return (
            f"enthalpies calculated by {PROPS_SOURCE} are on {thermo['state']} at "
            f"{thermo['temperature']:g} K, the flowsheet declares {ref.state} at "
            f"{ref.temperature:g} K (inconsistent reference)"
        )
    if process.reactive(node):
        if ref.state != "elements":
            return (
                "a reacting balance needs enthalpies on a heat-of-formation basis "
                f"(units.enthalpy_reference.state: elements); the reference is {ref.state}"
            )
        if by_props:
            return f"{PROPS_SOURCE} enthalpies do not include heats of formation"
    return ""


def energy_balance_of(process: Process, node: str, case: str) -> EnergyBalance:
    """The steady-state energy balance of block or step *node* in *case* (see the module
    docstring); streams with both ends inside cancel."""
    fs = process.flowsheet
    kind = process.kinds.get(node, "block")
    item = process.nodes.get(node)
    if isinstance(item, Block) and item.balance_scope == "dynamic":
        return EnergyBalance(node, kind, "unsupported", reason="balance_scope dynamic")

    def inside(node_id: str) -> bool:
        return node_id == node if kind == "step" else process.within(node_id, node)

    result = EnergyBalance(node, kind, "ok")
    comps = process.components()
    enthalpies = []
    flows_in: list[float] = []
    flows_out: list[float] = []
    material = 0
    for stream in fs.streams:
        if stream.kind == "information":
            continue
        a, b = process.ends(stream)
        if a is None or b is None or a.node not in process.kinds or b.node not in process.kinds:
            continue
        if inside(a.node) == inside(b.node):
            continue
        into = inside(b.node)
        state = stream.state.get(case)
        if stream.kind == "energy":
            result.energy_streams.append(stream.id)
            if state is None or state.duty is None:
                result.missing.append(f"{stream.id} duty")
                continue
            factor = DUTY_UNITS.get(state.duty.unit or fs.units.duty)
            if factor is None:
                result.missing.append(f"{stream.id} duty unit")
                continue
            if into:
                result.energy_in += state.duty.value * factor
            else:
                result.energy_out += state.duty.value * factor
            continue
        material += 1
        h = state.calculated.get("enthalpy") if state else None
        if h is None:
            result.missing.append(f"{stream.id} enthalpy")
            continue
        # read as kJ/kmol only when it is: another unit is cheme.process-unit, not converted
        unit = h.unit or fs.units.enthalpy
        if unit != CALCULATED_UNITS["enthalpy"]:
            result.missing.append(f"{stream.id} enthalpy in kJ/kmol (it is in {unit})")
            continue
        mm = state.calculated.get("molar_mass")
        if mm is not None and mm.unit not in (None, CALCULATED_UNITS["molar_mass"]):
            result.missing.append(f"{stream.id} molar mass in kg/kmol (it is in {mm.unit})")
            continue
        enthalpies.append(h)
        flows = stream_flows(process, stream, case)
        kmol_h = _molar_flow(flows, state, comps)
        if kmol_h is None:
            result.missing += flows.missing or [f"{stream.id} molar flow"]
            continue
        kw = kmol_h * h.value / 3600.0
        (flows_in if into else flows_out).append(kw)
    if not material:
        result.status = "no-streams"
        return result
    if result.missing:
        result.status = "not-evaluable"
        return result
    why = _reference_problem(process, enthalpies, node)
    if why:
        result.status, result.reason = "unsupported", why
        return result
    result.enthalpy_in, result.enthalpy_out = sum(flows_in), sum(flows_out)
    net = result.energy_in - result.energy_out
    result.residual = result.enthalpy_out - result.enthalpy_in - net
    if not result.energy_streams:
        result.status = "no-energy-streams"
        return result
    if kind == "block":
        # a step inside with an enthalpy change but no energy stream: its duty is undeclared,
        # so the block's energy streams cannot close it; nor when its enthalpy change is unknown
        for step in fs.steps:
            if not process.within(step.id, node):
                continue
            inner = energy_balance_of(process, step.id, case)
            if inner.status == "no-energy-streams" and abs(inner.residual or 0.0) > tolerance(
                0.0, abs(inner.enthalpy_in), abs(inner.enthalpy_out)
            ):
                result.missing.append(
                    f"the duty of step {step.id} (no energy stream; implied "
                    f"{inner.residual:.6g} kW)"
                )
            elif inner.status == "not-evaluable" and not inner.energy_streams:
                result.missing.append(
                    f"the duty of step {step.id} (no energy stream; not evaluable, missing "
                    f"{', '.join(inner.missing[:3])})"
                )
        if result.missing:
            result.status = "not-evaluable"
            return result
    result.tolerance = tolerance(
        result.energy_in + result.energy_out,
        sum(abs(x) for x in flows_in),
        sum(abs(x) for x in flows_out),
    )
    if abs(result.residual) > result.tolerance:
        result.status = "imbalance"
    return result


def _molar_flow(flows: Any, state: Any, comps: dict[str, Any]) -> float | None:
    """kmol/h from the mass flows: by the calculated molar mass, else by the components'."""
    if flows.total is None:
        return None
    mm = state.calculated.get("molar_mass") if state else None
    if mm is not None and mm.value > 0:
        return flows.total / mm.value
    if flows.components is None:
        return None
    total = 0.0
    for name, kg_h in flows.components.items():
        mw = getattr(comps.get(name), "molar_mass", None)
        if not mw:
            if kg_h:
                return None
            continue
        total += kg_h / mw
    return total


def energy_balances(process: Process, case: str | None = None) -> list[EnergyBalance]:
    case = case or process.flowsheet.default_case()
    found = [energy_balance_of(process, b.id, case) for b in process.flowsheet.blocks]
    found += [energy_balance_of(process, s.id, case) for s in process.flowsheet.steps]
    return found


def balance_findings(process: Process, found: list[EnergyBalance], case: str) -> list[Finding]:
    """``process-energy-balance`` and ``process-energy-balance-unsupported`` of *found*."""
    fs = process.flowsheet
    findings = []
    for result in found:
        key = "blocks" if result.kind == "block" else "steps"
        index = next(i for i, n in enumerate(getattr(fs, key)) if n.id == result.node)
        line = _yaml_line(process.flowsheet_doc, [key, index])
        if result.status == "imbalance":
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "warning",
                    "cheme.process-energy-balance",
                    f"{result.kind} {result.node} ({case}): enthalpy out minus in "
                    f"{result.enthalpy_out - result.enthalpy_in:.6g} kW, energy streams in minus "
                    f"out {result.energy_in - result.energy_out:.6g} kW: residual "
                    f"{result.residual or 0.0:.4g} kW (tolerance {result.tolerance or 0.0:.3g} kW)",
                    line=line,
                    ids=[result.node],
                    hint=f"energy streams: {', '.join(result.energy_streams)} -- check the duties "
                    "and the enthalpies (same property method and reference for all)",
                )
            )
        elif result.status == "unsupported" and not result.reason.startswith("balance_scope"):
            # (a dynamic scope: the mass balance already says so)
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "info",
                    "cheme.process-energy-balance-unsupported",
                    f"{result.kind} {result.node} ({case}): energy balance not evaluated: "
                    f"{result.reason}",
                    line=line,
                    ids=[result.node],
                    hint="unsupported/inconsistent enthalpy reference: no residual is reported",
                )
            )
    return findings


@dataclass
class EnergyReport:
    """``cheme process energy``: the flowsheet's energy balances (with their findings) and the
    energy audit of the recorded simulation run of the case (None without one)."""

    case: str
    balances: list[EnergyBalance]
    simulation: dict[str, Any] | None
    findings: list[Finding] = field(default_factory=list)

    def entry(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "balances": [b.entry() for b in self.balances],
            "simulation": self.simulation,
        }


def energy_report(root: Path, process: Process, case: str | None = None) -> EnergyReport:
    """The energy balances of *case* and the energy audit its simulation run recorded."""
    from chemeascode.domains.process.simulation import record

    case = case or process.flowsheet.default_case()
    entry = record.entry_of(record.read(Path(root)), case)
    audit = (entry or {}).get("energy")
    found = energy_balances(process, case)
    return EnergyReport(case, found, audit, balance_findings(process, found, case))


def energy_text(report: EnergyReport) -> str:
    """The report as ``cheme process energy`` prints it."""
    lines = [
        f"Energy balances, case {report.case} (kW; enthalpy flows on units.enthalpy_reference)"
    ]
    for b in report.balances:
        if b.status == "no-streams":
            continue
        text = f"{b.kind} {b.node}: {b.status}"
        if b.status in ("ok", "imbalance"):
            text += (
                f" (enthalpy in {b.enthalpy_in:.6g}, out {b.enthalpy_out:.6g}; energy in "
                f"{b.energy_in:.6g}, out {b.energy_out:.6g}; residual {b.residual:.4g}, "
                f"tolerance {b.tolerance:.3g})"
            )
        elif b.status == "no-energy-streams":
            text += f" (implied duty {b.residual:.6g})"
        if b.reason:
            text += f"; {b.reason}"
        if b.missing:
            text += (
                "; missing " + ", ".join(b.missing[:6]) + (", ..." if len(b.missing) > 6 else "")
            )
        lines.append(text)
    audit = report.simulation
    if audit is None:
        lines.append("Simulation: no energy audit recorded (run cheme process simulate --fill)")
        return "\n".join(lines)
    plant = audit["closure"]["plant"]
    lines.append(f"Simulation (recorded run), {audit['reference']['source']}:")
    if plant["status"] in ("ok", "imbalance"):
        lines.append(
            f"  plant closure {plant['status']}: residual {plant['residual_kW']:.4g} kW "
            f"(tolerance {plant['tolerance_kW']:.3g} kW)"
            + (", formation basis" if plant.get("basis") == "formation" else "")
        )
    else:
        lines.append(f"  plant closure {plant['status']}: {'; '.join(plant['reasons'])}")
    for row in audit["closure"]["units"]:
        if row["status"] in ("ok", "imbalance"):
            basis = " (formation basis)" if row.get("basis") == "formation" else ""
            lines.append(
                f"  {row['id']}: {row['status']}, residual {row['residual_kW']:.4g} kW{basis}"
            )
        else:
            reason = f": {row['reason']}" if row.get("reason") else ""
            lines.append(f"  {row['id']}: {row['status']}{reason}")
    for row in audit["exchangers"]:
        if "approach_K" in row:
            lines.append(
                f"  exchanger {row['id']}: least approach {row['approach_K']:.4g} K "
                f"({row['status']})"
            )
        else:
            lines.append(f"  exchanger {row['id']}: {row['status']}")
    for row in audit["utility_levels"]:
        lines.append(
            f"  {row['id']} ({row['role']}) from {row['terminal']}: {row['status']}"
            + (f", approach {row['approach_K']:.4g} K" if "approach_K" in row else "")
        )
    t = audit["utilities"]["totals_kW"]
    lines.append(
        f"  utilities: hot {t['hot_utility']:.4g}, cold {t['cold_utility']:.4g}, power in "
        f"{t['power_in']:.4g}, power out {t['power_out']:.4g}; recovered {t['recovered']:.4g} "
        "(process to process, not counted as utility)"
    )
    return "\n".join(lines)
