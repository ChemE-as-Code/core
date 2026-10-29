"""The DWSIM worker: reads ``{"model": ..., "save": path | null, "details": bool}`` (JSON) on
stdin, builds the flowsheet through DWSIM's Automation API, solves it and prints the result (JSON,
one line). With ``details`` each material stream also carries its density, molar mass, molar
enthalpy and the phases present, and the result the package's binary interaction parameters for
the model's compounds and its liquid-density settings (:func:`_details`, :func:`_package`): what
the property-package benchmark compares with reference equations of state.

Self-contained (standard library and pythonnet only): it runs inside the DWSIM image
(docker/dwsim/Dockerfile) or next to a local install, never inside cheme-as-code. DWSIM is found in
``CHEME_DWSIM_PATH`` (default ``/usr/local/lib/dwsim``); .NET is CoreCLR where the install
has a runtimeconfig (DWSIM 9 on Linux), else Mono (the macOS bundle). The native libraries
(``<path>`` and ``<path>/ThermoCS``) must be on ``LD_LIBRARY_PATH`` before the worker starts.

API names as in DWSIM 9.0.5 (DWSIM.UnitOperations, DWSIM.Interfaces, DWSIM.Automation).
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Any

DEFAULT_PATH = "/usr/local/lib/dwsim"
RUNTIME_CONFIG = "DWSIM.UI.Desktop.runtimeconfig.json"
ASSEMBLIES = (
    "DWSIM.Automation.dll",
    "DWSIM.Interfaces.dll",
    "DWSIM.GlobalSettings.dll",
    "DWSIM.SharedClasses.dll",
    "DWSIM.Thermodynamics.dll",
    "DWSIM.UnitOperations.dll",
    "DWSIM.FlowsheetBase.dll",
)
#: Property package name (simulation.yaml) -> class in DWSIM.Thermodynamics.PropertyPackages.
PACKAGES = {
    "Peng-Robinson (PR)": "PengRobinsonPropertyPackage",
    "Peng-Robinson 1978 (PR78)": "PengRobinson1978PropertyPackage",
    "Soave-Redlich-Kwong (SRK)": "SRKPropertyPackage",
    "NRTL": "NRTLPropertyPackage",
    "UNIQUAC": "UNIQUACPropertyPackage",
    "Steam Tables (IAPWS-IF97)": "SteamTablesPropertyPackage",
    "CoolProp": "CoolPropPropertyPackage",
}
#: cheme-as-code unit -> DWSIM ObjectType member.
OBJECTS = {
    "compressor": "Compressor",
    "pump": "Pump",
    "heater": "Heater",
    "cooler": "Cooler",
    "valve": "Valve",
    "mixer": "NodeIn",
    "splitter": "NodeOut",
    "expander": "Expander",
    "flash": "Vessel",
    "heat_exchanger": "HeatExchanger",
    "shortcut_column": "ShortcutColumn",
    "distillation_column": "DistillationColumn",
    "component_separator": "ComponentSeparator",
    "conversion_reactor": "RCT_Conversion",
    "equilibrium_reactor": "RCT_Equilibrium",
    "gibbs_reactor": "RCT_Gibbs",
}
#: The reactors: two outlets (vapour, liquid), an energy stream into connector 1.
REACTORS = ("conversion_reactor", "equilibrium_reactor", "gibbs_reactor")
#: Reaction phase (cheme-as-code) -> DWSIM's.
REACTION_PHASES = {"vapor": "Vapor", "liquid": "Liquid", "mixed": "Mixture"}
#: The outlets of a condensing unit (cooler, heater, intercooled compressor), in order.
CONDENSATE_ROLES = ["gas", "condensate"]
#: How a unit's energy streams connect, by the roles the model gives it (``energies``): role ->
#: (into the unit, inlet connector index; -1: the energy connector; None: the column's own
#: method). A unit without its energy stream in the model gets an internal one (the vessel
#: needs one in every mode).
ENERGY = {
    "compressor": {"energy": (True, -1)},
    "pump": {"energy": (True, -1)},
    "heater": {"energy": (True, -1)},
    "cooler": {"energy": (False, -1)},
    "expander": {"energy": (False, -1)},
    "flash": {"energy": (True, 6)},
    "shortcut_column": {"reboiler": (True, 1), "condenser": (False, -1)},
    "distillation_column": {"reboiler": (True, None), "condenser": (False, None)},
    "component_separator": {"energy": (False, -1)},
    **{kind: {"energy": (True, 1)} for kind in REACTORS},
}


#: Reflux ratios a column without condenser steps through: its top is a Full_Reflux condenser
#: holding back almost nothing, stepped down from where DWSIM converges.
REFLUX_STEPS = (0.05, 0.04, 0.03, 0.02, 0.015, 0.01)

#: A rigorous column's loop tolerances (inner and outer). DWSIM checks the solved column's
#: component balances to ten times the tighter of the two and fails the column beyond; with
#: its defaults (1e-5) a column missing by 1.3e-4, far inside the flowsheet tolerance, fails.
COLUMN_TOLERANCE = 1e-4


def _kmol_h(flow: dict[str, Any], mw: float) -> float:
    """A flow ``{"value", "basis"}`` (kg/h or kmol/h) in kmol/h, mass by molar mass *mw*."""
    return flow["value"] if flow["basis"] == "mole" else flow["value"] / mw


def _connect_column(sim: Any, unit: Any, u: dict[str, Any], objects: dict, torn: dict) -> None:
    """A rigorous column: stages, feeds by stage, products by what they carry, side draws.
    Without a condenser DWSIM gets one more stage on top (its Full_Reflux condenser)."""
    from DWSIM.UnitOperations.UnitOperations.Auxiliary.SepOps import StreamInformation as Info

    spec = u["spec"]
    extra = 1 if spec["condenser"] == "none" else 0
    unit.SetNumberOfStages(int(spec["stages"]) + extra)
    for s, stage in zip(u["inlets"], spec["feed_stages"], strict=True):
        # stages are numbered from 1 at the top; DWSIM's index from 0
        unit.ConnectFeed(objects[torn.get(s, s)], int(stage) - 1 + extra)
    names = u["roles"]
    products = dict(zip(names, u["outlets"], strict=False))
    if "vapor" in products:
        unit.ConnectVaporProduct(objects[products["vapor"]])
    if "distillate" in products:
        unit.ConnectDistillate(objects[products["distillate"]])
    unit.ConnectBottoms(objects[products["bottoms"]])
    for k, (sid, draw) in enumerate(
        zip(u["outlets"][len(names) :], spec["side_draws"], strict=True)
    ):
        stream = objects[sid]
        info = Info()
        info.ID = stream.Name
        info.StreamID = stream.Name
        info.AssociatedStage = unit.Stages[int(draw["stage"]) - 1 + extra].Name
        info.StreamBehavior = Info.Behavior.Sidedraw
        info.StreamType = Info.Type.Material
        info.StreamPhase = Info.Phase.V if draw["phase"] == "vapor" else Info.Phase.L
        info.FlowRate.Value = _kmol_h(draw, spec["mw_guess"]) / 3.6  # mol/s
        unit.MaterialStreams.Add(info.ID, info)
        # DWSIM's own methods take output connectors 0 (distillate), 1 (bottoms), 9 (vapour
        # product) and 10 (condenser duty); 2 to 8 are free for side draws
        sim.ConnectObjects(unit.GraphicObject, stream.GraphicObject, 2 + k, 0)


#: A tear has converged when its copy differs from it by at most this much: mass flow (kg/s,
#: summed over the compounds, as DWSIM's Recycle measures it), temperature (K), pressure (Pa).
#: DWSIM's defaults (0.01 kg/s, 0.1 K) stop short of the balance tolerance.
TEAR_TOLERANCE = (1e-7, 1e-4, 1e-2)
#: ... and the mass flow at most this fraction of the tear's flow where that is more than 1e-7
#: kg/s: DWSIM's unit models (equilibrium reactors above all) reproduce a loop's flows to
#: about 1e-6 of them (an ammonia loop, 85 kg/s, stalls at 3e-5 to 6e-4 kg/s at the converter
#: outlet), so 1e-7 kg/s on a large stream is met only by chance. 1e-5 stays 500 times inside
#: the default flowsheet balance tolerance of 0.5 % (ADR 0033).
TEAR_RELATIVE = 1e-5
#: Passes through the flowsheet one solve may take before its tears are reported.
TEAR_PASSES = 500
#: Earlier passes the tear iteration's acceleration (:func:`_anderson`) draws on.
ANDERSON_DEPTH = 5


def _tear_state(stream: Any) -> list[float]:
    """Temperature (K), pressure (Pa) and the compounds' mass flows (kg/s) of *stream*."""
    flows = [_num(c.MassFlow) or 0.0 for c in stream.Phases[0].Compounds.Values]
    return [_num(stream.GetTemperature()) or 0.0, _num(stream.GetPressure()) or 0.0, *flows]


def _tear_errors(tear: list[float], copy: list[float]) -> tuple[float, float, float]:
    """How far a copy is from its tear: mass flow (summed over the compounds), T, P."""
    mass = sum(abs(a - b) for a, b in zip(tear[2:], copy[2:], strict=True))
    return mass, abs(tear[0] - copy[0]), abs(tear[1] - copy[1])


def _tolerance(tear: list[float]) -> tuple[float, float, float]:
    """The tolerances of a tear (:data:`TEAR_TOLERANCE`, :data:`TEAR_RELATIVE`) by its state."""
    mass, kelvin, pascal = TEAR_TOLERANCE
    return max(mass, TEAR_RELATIVE * sum(tear[2:])), kelvin, pascal


def _anderson(xs: list[list[float]], gs: list[list[float]]) -> list[float]:
    """The next iterate of the fixed point x = g(x) from the last iterates *xs* and their images
    *gs* (oldest first): Anderson acceleration (Walker and Ni, SIAM J. Numer. Anal. 49 (2011)
    1715), the image minus the combination of earlier image steps that best cancels the
    residual f = g - x in the least-squares sense (modified Gram-Schmidt; a step that adds
    nothing new is dropped). A loop's tears in series give its slow mode complex eigenvalues,
    which a single dominant eigenvalue or a per-variable secant (Wegstein) cannot follow."""
    fs = [[g - x for g, x in zip(gk, xk, strict=True)] for xk, gk in zip(xs, gs, strict=True)]
    df = [[b - a for a, b in zip(fs[j], fs[j + 1], strict=True)] for j in range(len(fs) - 1)]
    dg = [[b - a for a, b in zip(gs[j], gs[j + 1], strict=True)] for j in range(len(gs) - 1)]
    q: list[list[float]] = []
    r: list[list[float]] = []  # column j of R: its coefficients on q[0..]
    kept: list[int] = []
    for j, col in enumerate(df):
        v, coef = list(col), []
        for qi in q:
            c = sum(a * b for a, b in zip(qi, v, strict=True))
            coef.append(c)
            v = [a - c * b for a, b in zip(v, qi, strict=True)]
        norm = math.sqrt(sum(a * a for a in v))
        if norm <= 1e-10 * math.sqrt(sum(a * a for a in col)) or norm == 0.0:
            continue
        q.append([a / norm for a in v])
        r.append([*coef, norm])
        kept.append(j)
    if not kept:
        return list(gs[-1])
    rhs = [sum(a * b for a, b in zip(qi, fs[-1], strict=True)) for qi in q]
    gamma = [0.0] * len(kept)
    for i in reversed(range(len(kept))):  # back substitution, R upper triangular
        s = rhs[i] - sum(r[k][i] * gamma[k] for k in range(i + 1, len(kept)))
        gamma[i] = s / r[i][i]
    out = list(gs[-1])
    for g, j in zip(gamma, kept, strict=True):
        out = [o - g * d for o, d in zip(out, dg[j], strict=True)]
    return out


class _Flowsheet:
    """Solves the flowsheet and counts the passes DWSIM's sequential solver makes through it.

    Without tears one ``CalculateFlowsheet4`` is one pass. With tears the worker iterates
    itself: each pass solves the flowsheet with the copies ("<id>-R") as given streams, then
    sets every copy at once from its tear, accelerated over all tears together
    (:func:`_anderson`), until every tear meets :data:`TEAR_TOLERANCE` or
    :data:`TEAR_PASSES` are spent. DWSIM's Recycle (9.0.5) only copies the tear (its
    GlobalBroyden leaves the composition unaccelerated), and a loop with a small purge relaxes
    by about the purge fraction per circuit: thousands of passes. Its Recycle blocks are
    connected afterwards (:meth:`close`) and run their own test on the converged flowsheet."""

    def __init__(self, automation: Any, sim: Any, tears: dict[str, tuple[Any, Any]]) -> None:
        self.automation, self.sim = automation, sim
        self.tears = tears  # tear id -> (tear stream, its copy)
        self.recycles: list[Any] = []  # DWSIM's Recycle blocks, once connected
        self.passes = 0
        self.unconverged: dict[str, tuple[float, float, float]] = {}

    def _pass(self) -> list[str]:
        errors = self.automation.CalculateFlowsheet4(self.sim) or []
        taken = [int(_num(r.IterationsTaken) or 0) for r in self.recycles]
        self.passes += max([1, *taken])
        return [str(getattr(e, "Message", e)) for e in errors]

    def solve(self) -> list[str]:
        """The solve's error messages (none: it converged)."""
        if not self.tears or self.recycles:
            return self._pass()
        ids = list(self.tears)
        scale = [TEAR_TOLERANCE[1], TEAR_TOLERANCE[2]]  # residuals in tolerances
        xs: list[list[float]] = []
        gs: list[list[float]] = []
        accelerated, unit = False, scale
        for _ in range(TEAR_PASSES):
            errors = self._pass()
            if errors and accelerated and gs:
                # the accelerated copies failed a unit: back to the last tears, copied plainly
                self._set(ids, gs[-1], unit)
                xs, gs, accelerated = [], [], False
                continue
            if errors:
                return errors
            states = {t: [_tear_state(s) for s in self.tears[t]] for t in ids}
            self.unconverged = {}
            for t in ids:
                found = _tear_errors(*states[t])
                if any(e > tol for e, tol in zip(found, _tolerance(states[t][0]), strict=True)):
                    self.unconverged[t] = found
            if not self.unconverged:
                return []
            unit = scale + [TEAR_TOLERANCE[0]] * (len(states[ids[0]][0]) - 2)
            xs.append([v / u for t in ids for v, u in zip(states[t][1], unit, strict=True)])
            gs.append([v / u for t in ids for v, u in zip(states[t][0], unit, strict=True)])
            xs, gs = xs[-ANDERSON_DEPTH - 1 :], gs[-ANDERSON_DEPTH - 1 :]
            accelerated = len(xs) > 1
            self._set(ids, _anderson(xs, gs) if accelerated else gs[-1], unit)
        return [
            f"recycle at {t}: not converged in {TEAR_PASSES} passes (copy off by {m:.3g} kg/s, "
            f"{dt:.3g} K, {dp:.3g} Pa; tolerance {tol[0]:.3g} kg/s, {tol[1]:g} K, {tol[2]:g} Pa)"
            for t, (m, dt, dp) in self.unconverged.items()
            for tol in [_tolerance(_tear_state(self.tears[t][0]))]
        ]

    def _set(self, ids: list[str], x: list[float], unit: list[float]) -> None:
        """Set the copies from the scaled iterate *x* (the tears' variables in order)."""
        from System import Array, Double

        n = len(unit)
        for k, t in enumerate(ids):
            v = [a * u for a, u in zip(x[k * n : (k + 1) * n], unit, strict=True)]
            copy = self.tears[t][1]
            flows = [max(w, 0.0) for w in v[2:]]
            weights = [c.ConstantProperties.Molar_Weight for c in copy.Phases[0].Compounds.Values]
            moles = [w / mw for w, mw in zip(flows, weights, strict=True)]
            copy.SetTemperature(v[0] if v[0] > 0 else self.tears[t][0].GetTemperature())
            copy.SetPressure(v[1] if v[1] > 0 else self.tears[t][0].GetPressure())
            copy.SetMassFlow(sum(flows))
            if sum(moles) > 0:
                copy.SetOverallComposition(Array[Double]([m / sum(moles) for m in moles]))

    def close(self, sim: Any, kind: Any, converged: bool) -> list[str]:
        """Connect DWSIM's Recycle blocks between the tears and their copies (as the saved
        flowsheet shows them) and, when the tear iteration converged, let DWSIM run its own
        recycle test on it, which then passes in its first pass; why not where not."""
        messages = []
        for k, (t, (tear, copy)) in enumerate(self.tears.items()):
            recycle = _concrete(sim.AddObject(kind, 100 + 150 * k, 500, f"RC-{t}"))
            sim.ConnectObjects(tear.GraphicObject, recycle.GraphicObject, -1, 0)
            sim.ConnectObjects(recycle.GraphicObject, copy.GraphicObject, 0, -1)
            limits = recycle.ConvergenceParameters
            limits.VazaoMassica, limits.Temperatura, limits.Pressao = _tolerance(_tear_state(tear))
            recycle.MaximumIterations = TEAR_PASSES
            self.recycles.append(recycle)
        if not converged or not self.recycles:
            return messages
        messages += self._pass()
        for t, recycle in zip(self.tears, self.recycles, strict=True):
            if not recycle.Converged:
                h = recycle.ConvergenceHistory
                messages.append(
                    f"recycle at {t}: not converged in DWSIM's recycle test (copy off by "
                    f"{abs(_num(h.VazaoMassicaE) or 0):.3g} kg/s, "
                    f"{abs(_num(h.TemperaturaE) or 0):.3g} K, {abs(_num(h.PressaoE) or 0):.3g} Pa)"
                )
        return messages


def _columns(flowsheet: _Flowsheet, objects: dict, model: dict) -> list[str]:
    """After the first solve: bring the columns without condenser down the reflux steps, and
    the mass flows of vapour products and side draws to their targets; why not where not."""
    columns = [u for u in model["units"] if u["type"] == "distillation_column"]
    messages: list[str] = []
    solve = flowsheet.solve

    for u in [c for c in columns if c["spec"]["condenser"] == "none"]:
        unit, good = objects[u["id"]], REFLUX_STEPS[0]
        for ratio in REFLUX_STEPS[1:]:
            unit.SetCondenserSpec("Stream_Ratio", ratio, "", "")
            if not solve():
                good = ratio
                continue
            # a step too far: back to the last ratio that converged, its profile restored
            unit.SetCondenserSpec("Stream_Ratio", good, "", "")
            errors = solve()
            if errors:
                return errors
            break

    def targets(apply: bool) -> float:
        moved = 0.0
        for u in columns:
            spec, unit = u["spec"], objects[u["id"]]
            products = u["outlets"]
            if spec.get("vapor_flow") and spec["vapor_flow"]["basis"] == "mass":
                stream = objects[products[0]]
                moved = max(moved, _retarget(unit, stream, spec["vapor_flow"], True, apply))
            drawn = products[len(products) - len(spec["side_draws"]) :]
            for sid, draw in zip(drawn, spec["side_draws"], strict=True):
                if draw["basis"] == "mass":
                    moved = max(moved, _retarget(unit, objects[sid], draw, False, apply))
        return moved

    for _ in range(8):
        if targets(apply=True) < 1e-5:
            return messages
        errors = solve()
        if errors:
            return errors
    if targets(apply=False) < 1e-4:
        return messages
    return messages + ["a column's mass flow targets did not converge"]


def _retarget(unit: Any, stream: Any, flow: dict, vapor: bool, apply: bool = True) -> float:
    """Set (*apply*) a vapour product's or side draw's molar flow from its solved molar mass so
    that it meets its mass flow; return the relative change it needs."""
    mass, molar = _num(stream.GetMassFlow()) or 0.0, _num(stream.GetMolarFlow()) or 0.0
    if mass <= 0 or molar <= 0:
        return 0.0
    mw = mass / molar  # kg/mol
    target = flow["value"] / 3600.0 / mw  # mol/s
    if vapor:
        old = unit.VaporFlowRate / 3.6
        if apply:
            unit.VaporFlowRate = target * 3.6
    else:
        info = next(i for i in unit.MaterialStreams.Values if i.StreamID == stream.Name)
        old = info.FlowRate.Value
        if apply:
            info.FlowRate.Value = target
    return abs(target - old) / max(target, 1e-12)


def _expand(model: dict[str, Any]) -> dict[str, list[str]]:
    """Replace each multi-stream exchanger in *model* by one heater per stream (``<id>/<k>``);
    return exchanger id -> its heaters. A heater without an outlet temperature closes the energy
    balance (its duty is set in :func:`_balance`)."""
    groups: dict[str, list[str]] = {}
    units = []
    for u in model["units"]:
        if u["type"] != "multi_stream_exchanger":
            units.append(u)
            continue
        groups[u["id"]] = []
        for k, (inlet, outlet, side) in enumerate(
            zip(u["inlets"], u["outlets"], u["spec"]["sides"], strict=True)
        ):
            spec = {"pressure_drop_Pa": side["pressure_drop_Pa"]}
            if side["outlet_temperature_K"] is not None:
                spec["outlet_temperature_K"] = side["outlet_temperature_K"]
            else:
                spec["duty_kW"] = 0.0
            sub = f"{u['id']}/{k}"
            groups[u["id"]].append(sub)
            units.append(
                {
                    "id": sub,
                    "type": "heater",
                    "inlets": [inlet],
                    "outlets": [outlet],
                    "energies": {"energy": None},
                    "spec": spec,
                }
            )
    model["units"] = units
    return groups


def _expand_trains(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Replace each compressor with intercoolers in *model* by its stages and coolers
    (``<id>/C<k>``, ``<id>/E<k>``); return compressor id -> its train. The stage pressures are
    set in :func:`_pressures` once the inlet pressure is known."""
    trains: dict[str, dict[str, Any]] = {}
    units = []
    for u in model["units"]:
        spec = u["spec"]
        if u["type"] != "compressor" or "stages" not in spec:
            units.append(u)
            continue
        train = {
            "inlet": u["inlets"][0],
            "compressors": [],
            "coolers": [],
            "spec": spec,
        }
        before = u["inlets"][0]
        # with a condensate outlet, each cooler's liquid is flashed off and the drains joined
        gas = u["outlets"][0]
        drain = u["outlets"][1] if u.get("roles") == CONDENSATE_ROLES else None
        liquids: list[str] = []
        # stages start in pressure-ratio mode (never below their inlet), from the feed pressure
        # where the inlet is a feed; _pressures sets the exact ratio from the solved inlet
        feed = next(
            (s["feed"] for s in model["streams"] if s["id"] == before and s.get("feed")), None
        )
        start = feed["pressure_Pa"] if feed else 101325.0
        target = spec.get("outlet_pressure_Pa") or start + spec["pressure_increase_Pa"]
        ratio = max(target / start, 1.0) ** (1.0 / int(spec["stages"]))
        stages = int(spec["stages"])
        for k in range(1, stages + 1):
            hot = f"{u['id']}#c{k}"
            cold = gas if k == stages else f"{u['id']}#k{k}"
            wet = f"{u['id']}#w{k}" if drain else cold
            internal = [hot] + ([cold] if cold != gas else []) + ([wet] if drain else [])
            model["streams"] += [{"id": s, "kind": "material", "feed": None} for s in internal]
            for sub, kind, ins, outs, sub_spec in (
                (
                    f"{u['id']}/C{k}",
                    "compressor",
                    before,
                    hot,
                    {"pressure_ratio": ratio, "efficiency": spec["efficiency"]},
                ),
                (
                    f"{u['id']}/E{k}",
                    "cooler",
                    hot,
                    wet,
                    {
                        "outlet_temperature_K": spec["outlet_temperature_K"],
                        "pressure_drop_Pa": spec["cooler_pressure_drop_Pa"],
                    },
                ),
            ):
                units.append(
                    {
                        "id": sub,
                        "type": kind,
                        "inlets": [ins],
                        "outlets": [outs],
                        "energies": {"energy": None},
                        "spec": sub_spec,
                    }
                )
                train["compressors" if kind == "compressor" else "coolers"].append(sub)
            if drain:
                liquid = drain if stages == 1 else f"{u['id']}#l{k}"
                if liquid != drain:
                    model["streams"].append({"id": liquid, "kind": "material", "feed": None})
                units.append(_knockout(f"{u['id']}/K{k}", wet, cold, liquid))
                liquids.append(liquid)
            before = cold
        if drain and stages > 1:
            units.append(
                {
                    "id": f"{u['id']}/M",
                    "type": "mixer",
                    "inlets": liquids,
                    "outlets": [drain],
                    "energies": {},
                    "spec": {},
                    "internal": True,
                }
            )
        trains[u["id"]] = train
        # the machine's own energy streams get its power and cooling from the results
        own = {e for e in u.get("energies", {}).values() if e}
        model["streams"] = [s for s in model["streams"] if s["id"] not in own]
    model["units"] = units
    return trains


def _knockout(name: str, wet: str, gas: str, liquid: str) -> dict[str, Any]:
    """A flash drum at its inlet's conditions: the condensate off a cooled stream."""
    return {
        "id": name,
        "type": "flash",
        "inlets": [wet],
        "outlets": [gas, liquid],
        "energies": {"energy": None},
        "spec": {},
        "internal": True,
    }


def _expand_drains(model: dict[str, Any]) -> None:
    """Give each heater or cooler with a condensate outlet a flash drum after it
    (``<id>/K``)."""
    units = []
    for u in model["units"]:
        units.append(u)
        if u["type"] not in ("heater", "cooler") or u.get("roles") != CONDENSATE_ROLES:
            continue
        gas, drain = u["outlets"]
        wet = f"{u['id']}#w"
        model["streams"].append({"id": wet, "kind": "material", "feed": None})
        u["outlets"] = [wet]
        units.append(_knockout(f"{u['id']}/K", wet, gas, drain))
    model["units"] = units


def _expand_reactor_liquids(model: dict[str, Any]) -> None:
    """DWSIM's reactors have a vapour and a liquid outlet: a reactor with one outlet in the
    model gets an internal liquid outlet ``<id>#liq``, checked to stay empty after the solve."""
    for u in model["units"]:
        if u["type"] in REACTORS and len(u["outlets"]) == 1:
            liquid = f"{u['id']}#liq"
            model["streams"].append(
                {"id": liquid, "kind": "material", "feed": None, "internal": True}
            )
            u["outlets"] = [*u["outlets"], liquid]
            u["hidden_liquid"] = liquid


def _reactions(sim: Any, u: dict[str, Any], names: dict[str, str]) -> str:
    """The reaction set of reactor *u* (its own, ``RS-<id>``), with its reactions; its id."""
    from System import Double, String
    from System.Collections.Generic import Dictionary

    reaction_set = sim.CreateReactionSet(f"RS-{u['id']}", "")
    sim.AddReactionSet(reaction_set)
    for r in u["spec"].get("reactions", []):
        coefficients = Dictionary[String, Double]()
        for cid, nu in r["stoichiometry"].items():
            coefficients[names[cid]] = float(nu)
        name = f"{u['id']}:{r['id']}"
        phase = REACTION_PHASES[r["phase"]]
        if r["type"] == "conversion":
            # DWSIM's conversion is in percent of the base compound
            reaction = sim.CreateConversionReaction(
                name, "", coefficients, names[r["base"]], phase, repr(100.0 * r["conversion"])
            )
        else:
            # ln K on partial pressures in bar; no expression: DWSIM's own Gibbs energies
            reaction = sim.CreateEquilibriumReaction(
                name,
                "",
                coefficients,
                names[r["base"]],
                phase,
                "Partial Pressure",
                "bar",
                float(r.get("approach_K", 0.0)),
                r.get("ln_k", ""),
            )
        sim.AddReaction(reaction)
        # one rank for all: the reactions run in parallel on the reactor's inlet, as cheme
        # process propagate converts every key component's inlet flow at once
        sim.AddReactionToSet(reaction.ID, reaction_set.ID, True, 0)
    return reaction_set.ID


def _pressures(objects: dict, trains: dict) -> tuple[bool, list[str]]:
    """Set the stage pressure ratio of every train, equal for all stages, from its solved inlet
    pressure to the target after the last cooler; whether any changed, and the trains whose
    target is below what their coolers' pressure drops leave of the inlet pressure."""
    changed = False
    problems = []
    for name, train in trains.items():
        spec = train["spec"]
        inlet = _num(objects[train["inlet"]].GetPressure()) or 101325.0
        target = spec.get("outlet_pressure_Pa") or inlet + spec["pressure_increase_Pa"]
        drop, n = spec["cooler_pressure_drop_Pa"], len(train["compressors"])

        def end(ratio: float, inlet: float = inlet, drop: float = drop, n: int = n) -> float:
            p = inlet
            for _ in range(n):
                p = p * ratio - drop
            return p

        if end(1.0) > target + 1.0:
            problems.append(
                f"{name}: outlet pressure {target / 1e5:.4g} bar(a) is below the inlet "
                f"{inlet / 1e5:.4g} bar(a) less the cooler pressure drops"
            )
            continue
        lo, hi = 1.0, 2.0
        while end(hi) < target:
            hi *= 2.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if end(mid) < target else (lo, mid)
        for stage in train["compressors"]:
            if abs((_num(objects[stage].PressureRatio) or 0.0) - hi) > 1e-9:
                objects[stage].PressureRatio = hi
                changed = True
    return changed, problems


def _balance(flowsheet: _Flowsheet, objects: dict, groups: dict, model: dict) -> list[str]:
    """Iterate the free stream of each multi-stream exchanger until the exchanger's duties add
    up to zero; return why not where they do not."""
    specs = {u["id"]: u["spec"] for u in model["units"]}
    free = {g: [s for s in subs if "duty_kW" in specs[s]] for g, subs in groups.items()}
    free = {g: f[0] for g, f in free.items() if f}
    messages = []
    for _ in range(30):
        moved = 0.0
        for g, sub in free.items():
            others = sum(_num(objects[s].DeltaQ) or 0.0 for s in groups[g] if s != sub)
            moved = max(moved, abs((_num(objects[sub].DeltaQ) or 0.0) + others))
            objects[sub].DeltaQ = -others
        if moved < 1e-6:
            return messages
        errors = flowsheet.solve()
        if errors:
            return errors
    messages += [f"{g}: the energy balance did not close" for g in free]
    return messages


def _load(path: str) -> Any:
    """Load .NET and DWSIM; return the namespaces used."""
    from pythonnet import load

    config = os.path.join(path, RUNTIME_CONFIG)
    if os.path.isfile(config):
        load("coreclr", runtime_config=config)
    else:
        load("mono")
    os.chdir(path)
    sys.path.append(path)
    import clr

    for name in ASSEMBLIES:
        clr.AddReference(os.path.join(path, name))
    from System.IO import Directory

    Directory.SetCurrentDirectory(path)
    import DWSIM.Thermodynamics.PropertyPackages as packages
    import DWSIM.UnitOperations.UnitOperations as unitops
    from DWSIM.Automation import Automation3
    from DWSIM.GlobalSettings import Settings
    from DWSIM.Interfaces.Enums.GraphicObjects import ObjectType

    return Automation3, Settings, ObjectType, packages, unitops


def _concrete(obj: Any) -> Any:
    """The concrete .NET object behind an interface wrapper."""
    obj = obj.GetAsObject() if hasattr(obj, "GetAsObject") else obj
    return getattr(obj, "__implementation__", obj)


def _compound_names(automation: Any, compounds: list[dict[str, Any]]) -> dict[str, str]:
    """Compound id -> DWSIM compound name: the given name, else by CAS number, else by title."""
    available = automation.AvailableCompounds
    by_cas = {}
    names = set()
    for key in available.Keys:
        names.add(str(key))
        cas = str(getattr(available[key], "CAS_Number", "") or "")
        if cas:
            by_cas.setdefault(cas, str(key))
    found = {}
    for c in compounds:
        name = (
            c.get("name")
            or by_cas.get(c.get("cas") or "")
            or (c.get("title") if c.get("title") in names else None)
        )
        if not name or name not in names:
            raise LookupError(
                f"compound {c['id']} (CAS {c.get('cas') or '?'}) is not in the DWSIM database; "
                "give its DWSIM name under components: in process/simulation.yaml"
            )
        found[c["id"]] = name
    return found


def _interactions(pp: Any, pairs: list[dict[str, Any]], names: dict[str, str]) -> None:
    """Set the kij of the equation-of-state package *pp* for *pairs*. DWSIM keeps one entry per
    pair under either compound; an existing entry is overwritten in whichever order it is, a
    missing one is added."""
    if not pairs:
        return
    from DWSIM.Thermodynamics.PropertyPackages.Auxiliary import PR_IPData
    from System import String
    from System.Collections.Generic import Dictionary

    table = pp.m_pr.InteractionParameters
    for p in pairs:
        a, b = (names[c] for c in p["components"])
        entries = [
            table[x][y]
            for x, y in ((a, b), (b, a))
            if table.ContainsKey(x) and table[x].ContainsKey(y)
        ]
        if not entries:
            if not table.ContainsKey(a):
                table.Add(a, Dictionary[String, PR_IPData]())
            entry = PR_IPData()
            entry.Name1, entry.Name2 = a, b
            table[a].Add(b, entry)
            entries = [entry]
        for entry in entries:
            entry.kij = float(p["kij"])


def solve(request: dict[str, Any]) -> dict[str, Any]:
    model = request["model"]
    path = os.environ.get("CHEME_DWSIM_PATH", DEFAULT_PATH)
    Automation3, Settings, ObjectType, packages, unitops = _load(path)
    from System import Array, Double

    automation = Automation3()
    sim = automation.CreateFlowsheet()
    names = _compound_names(automation, model["compounds"])
    for c in model["compounds"]:
        sim.AddCompound(names[c["id"]])
    package = PACKAGES.get(model["property_package"])
    if package is None:
        raise LookupError(
            f"property package {model['property_package']!r} is not supported; one of "
            + ", ".join(PACKAGES)
        )
    pp = getattr(packages, package)()
    sim.AddPropertyPackage(pp)
    _interactions(pp, model.get("interaction_parameters", []), names)

    objects: dict[str, Any] = {}
    groups = _expand(model)
    trains = _expand_trains(model)
    _expand_drains(model)
    _expand_reactor_liquids(model)
    order = {u["id"]: i for i, u in enumerate(model["units"])}
    for i, s in enumerate(model["streams"]):
        kind = ObjectType.MaterialStream if s["kind"] == "material" else ObjectType.EnergyStream
        objects[s["id"]] = _concrete(sim.AddObject(kind, 100 + 150 * i, 100, s["id"]))
    for u in model["units"]:
        x = 175 + 150 * order[u["id"]]
        objects[u["id"]] = _concrete(
            sim.AddObject(getattr(ObjectType, OBJECTS[u["type"]]), x, 250, u["id"])
        )
    # a tear stream leaves its unit as itself and enters the next one as its copy "<id>-R",
    # with a DWSIM Recycle between the two
    torn = {r["stream"]: f"{r['stream']}-R" for r in model.get("recycles", [])}
    for copy in torn.values():
        objects[copy] = _concrete(sim.AddObject(ObjectType.MaterialStream, 100, 550, copy))
    for u in model["units"]:
        unit = objects[u["id"]]
        if u["type"] == "distillation_column":
            _connect_column(sim, unit, u, objects, torn)
        else:
            for k, s in enumerate(u["inlets"]):
                sim.ConnectObjects(objects[torn.get(s, s)].GraphicObject, unit.GraphicObject, -1, k)
            for k, s in enumerate(u["outlets"]):
                sim.ConnectObjects(unit.GraphicObject, objects[s].GraphicObject, k, -1)
        roles = dict(u.get("energies", {}))
        if u["type"] == "distillation_column":
            # DWSIM's column always has both duties; a missing condenser or reboiler is a
            # Full_Reflux condenser near zero duty and a reboiler at zero duty
            roles = {"reboiler": roles.get("reboiler"), "condenser": roles.get("condenser")}
        for role, given in roles.items():
            into, index = ENERGY[u["type"]][role]
            energy = given or f"{role[0].upper()}-{u['id']}"
            if energy not in objects:
                objects[energy] = _concrete(
                    sim.AddObject(ObjectType.EnergyStream, 175 + 150 * order[u["id"]], 400, energy)
                )
            e = objects[energy].GraphicObject
            if index is None:
                if into:
                    unit.ConnectReboilerDuty(objects[energy])
                else:
                    unit.ConnectCondenserDuty(objects[energy])
            elif into:
                sim.ConnectObjects(e, unit.GraphicObject, -1, index)
            else:
                sim.ConnectObjects(unit.GraphicObject, e, -1, -1)
        if u["type"] in REACTORS:
            unit.ReactionSetID = _reactions(sim, u, names)
        _specify(unit, u, unitops, names)

    order_ids = [str(k) for k in sim.SelectedCompounds.Keys]
    by_name = {v: k for k, v in names.items()}
    for s in model["streams"]:
        feed = s.get("feed")
        if not feed:
            continue
        ms = objects[s["id"]]
        if feed.get("vapor_fraction") is not None:
            # a saturation state: DWSIM finds the temperature at this pressure and vapour fraction
            from DWSIM.Interfaces.Enums import StreamSpec

            ms.SpecType = StreamSpec.Pressure_and_VaporFraction
            ms.Phases[2].Properties.molarfraction = float(feed["vapor_fraction"])
        else:
            ms.SetTemperature(float(feed["temperature_K"]))
        ms.SetPressure(float(feed["pressure_Pa"]))
        ms.SetMassFlow(float(feed["mass_flow_kg_s"]))
        x = [float(feed["mole_fractions"].get(by_name.get(n, ""), 0.0)) for n in order_ids]
        ms.SetOverallComposition(Array[Double](x))

    first = next((s["feed"] for s in model["streams"] if s.get("feed")), None)
    for r in model.get("recycles", []):
        sid = r["stream"]
        guess = {**(first or {}), **(r.get("guess") or {})}
        copy = objects[torn[sid]]
        copy.SetTemperature(float(guess.get("temperature_K", 298.15)))
        copy.SetPressure(float(guess.get("pressure_Pa", 101325.0)))
        copy.SetMassFlow(float(guess.get("mass_flow_kg_s", 0.0)))
        fractions = guess.get("mole_fractions") or {}
        copy.SetOverallComposition(
            Array[Double]([float(fractions.get(by_name.get(n, ""), 0.0)) for n in order_ids])
        )

    Settings.SolverMode = 0
    flowsheet = _Flowsheet(automation, sim, {t: (objects[t], objects[c]) for t, c in torn.items()})
    messages = flowsheet.solve()
    for _ in range(10 if trains else 0):
        # a first pass that failed on a starting ratio is redone from the solved inlet pressure
        changed, problems = _pressures(objects, trains)
        if problems:
            messages += problems
            break
        if not changed:
            break
        messages = flowsheet.solve()
    if not messages and any(u["type"] == "distillation_column" for u in model["units"]):
        messages = _columns(flowsheet, objects, model)
    if groups and not messages:
        messages += _balance(flowsheet, objects, groups, model)
    messages += flowsheet.close(sim, ObjectType.OT_Recycle, not messages)
    for key, obj in objects.items():
        if hasattr(obj, "Calculated") and not obj.Calculated:
            text = str(getattr(obj, "ErrorMessage", "") or "")
            messages.append(f"{key}: not calculated" + (f" ({text})" if text else ""))
    save_error = None
    if request.get("save"):
        try:
            os.makedirs(os.path.dirname(request["save"]) or ".", exist_ok=True)
            automation.SaveFlowsheet(sim, request["save"], True)
        except Exception as failure:  # noqa: BLE001 - the results stand without the file
            save_error = f"{type(failure).__name__}: {failure}"

    for u in model["units"]:
        liquid = u.get("hidden_liquid")
        flow = _num(objects[liquid].GetMassFlow()) if liquid else None
        if flow is not None and math.isfinite(flow) and flow > 1e-9:
            messages.append(
                f"{u['id']}: {flow * 3600:.6g} kg/h of liquid formed in the reactor, which has one "
                "outlet; give the step a liquid outlet (port liquid) or change its conditions"
            )
    streams: dict[str, Any] = {}
    energies: dict[str, Any] = {}
    for s in model["streams"]:
        if s.get("internal"):
            continue
        obj = objects[s["id"]]
        if s["kind"] == "energy":
            energies[s["id"]] = {"duty_kW": _num(obj.EnergyFlow)}
            continue
        composition = list(obj.GetOverallComposition())
        vapour = None
        try:
            vapour = _num(obj.GetPhase("Vapor").Properties.molarfraction)
        except Exception:  # noqa: BLE001 - a stream without the phase
            vapour = None
        enthalpy = None
        try:  # kJ/kg on DWSIM's own reference (for energy balances within this run only)
            enthalpy = _num(obj.GetMassEnthalpy())
        except Exception:  # noqa: BLE001 - the stream values stand without it
            enthalpy = None
        if enthalpy is not None and not math.isfinite(enthalpy):
            enthalpy = None
        streams[s["id"]] = {
            "mass_enthalpy_kJ_kg": enthalpy,
            "temperature_K": _num(obj.GetTemperature()),
            "pressure_Pa": _num(obj.GetPressure()),
            "mass_flow_kg_s": _num(obj.GetMassFlow()),
            "molar_flow_mol_s": _num(obj.GetMolarFlow()),
            "mole_fractions": {
                by_name[n]: float(v) for n, v in zip(order_ids, composition, strict=False)
            },
            "vapor_fraction": vapour,
        }
        if request.get("details"):
            streams[s["id"]].update(_details(obj, by_name, s.get("feed")))
    units: dict[str, Any] = {}
    for u in model["units"]:
        obj = objects[u["id"]]
        kind = u["type"]
        if kind in ("compressor", "pump", "heater", "flash", "expander"):
            # power taken (compressor, pump), produced (expander), heat added (heater, flash)
            units[u["id"]] = {"duty_kW": _num(obj.DeltaQ)}
        elif kind == "cooler":
            q = _num(obj.DeltaQ)
            units[u["id"]] = {"duty_kW": -q if q is not None else None}
        elif kind == "heat_exchanger":
            units[u["id"]] = {"duty_kW": _num(obj.Q)}
        elif kind == "component_separator":
            units[u["id"]] = {"duty_kW": _num(obj.EnergyImb)}
        elif kind in REACTORS:
            # heat added (negative: removed); the extents in kmol/h by reaction id
            extents = {}
            # the conversion reactor keeps no extents (its conversions say them)
            for key, value in dict(getattr(obj, "ReactionExtents", None) or {}).items():
                rid = str(key).removeprefix(f"{u['id']}:")
                extents[rid] = (_num(value) or 0.0) * 3.6
            units[u["id"]] = {"duty_kW": _num(obj.DeltaQ), "extents_kmol_h": extents}
        elif kind == "distillation_column":
            spec = u["spec"]
            units[u["id"]] = {
                "condenser_kW": _abs(obj.CondenserDuty) if spec["condenser"] != "none" else None,
                "top_residual_kW": _num(obj.CondenserDuty) if spec["condenser"] == "none" else None,
                "reboiler_kW": _abs(obj.ReboilerDuty) if spec["reboiler"] else None,
                "reflux_ratio": _num(obj.RefluxRatio) if spec["condenser"] != "none" else None,
                "top_temperature_K": _num(obj.Stages[0].T),
                "bottom_temperature_K": _num(obj.Stages[obj.Stages.Count - 1].T),
            }
        elif kind == "shortcut_column":
            units[u["id"]] = {
                "condenser_kW": _abs(obj.m_Qc),
                "reboiler_kW": _abs(obj.m_Qb),
                "min_reflux": _num(obj.m_Rmin),
                "min_stages": _num(obj.m_Nmin),
                "stages": _num(obj.m_N),
            }
    for name, train in trains.items():
        units[name] = {
            "duty_kW": sum(_num(objects[c].DeltaQ) or 0.0 for c in train["compressors"]),
            "cooling_kW": sum(_num(objects[c].DeltaQ) or 0.0 for c in train["coolers"]),
        }
        for sub in train["compressors"] + train["coolers"]:
            units.pop(sub, None)
    for u in model["units"]:
        if u.get("internal"):  # drums and drain mixers the worker added
            units.pop(u["id"], None)
    for g, subs in groups.items():
        duties = [_num(objects[s].DeltaQ) or 0.0 for s in subs]
        units[g] = {
            "duty_kW": sum(q for q in duties if q > 0),
            "imbalance_kW": sum(duties),
            # heat added to each stream, by inlet in port order (negative: given up)
            "side_duties_kW": duties,
        }
        for s in subs:
            units.pop(s, None)
    package_details = _package(pp, names) if request.get("details") else {}
    return {
        **package_details,
        "ok": True,
        "version": _version(str(automation.GetVersion())),
        "converged": not messages,
        "iterations": flowsheet.passes,
        "messages": messages,
        "streams": streams,
        "energies": energies,
        "units": units,
        "compounds": _compound_data(automation, names),
        "save_error": save_error,
    }


#: DWSIM's phase index -> the name in :func:`_details` (0 is the mixture).
PHASES = {2: "vapor", 3: "liquid", 4: "liquid2"}


#: A saturation feed's vapour fraction -> the phase DWSIM holds the incipient composition in
#: (vapour at the bubble point, liquid at the dew point), with its name in :func:`_details`.
INCIPIENT = {0.0: (2, "vapor"), 1.0: (3, "liquid")}


def _details(
    obj: Any, by_name: dict[str, str], feed: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A solved material stream's density (kg/m3), molar mass (kg/kmol), molar enthalpy
    (kJ/kmol, DWSIM's reference) and the phases present (molar fraction > 0) with their
    densities and mole fractions by compound id. A feed at its bubble or dew point (vapour
    fraction 0 or 1) also has ``incipient``: the phase in equilibrium with it that is not
    present, and its mole fractions."""

    def props(phase: Any) -> dict[str, Any]:
        p = phase.Properties
        return {
            "density_kg_m3": _num(p.density),
            "molar_enthalpy_kJ_kmol": _num(p.molar_enthalpy),
        }

    mixture = obj.Phases[0]
    phases = {}
    for index, name in PHASES.items():
        phase = obj.Phases[index]
        fraction = _num(phase.Properties.molarfraction)
        if fraction is None or not math.isfinite(fraction) or fraction <= 0:
            continue
        phases[name] = {
            "fraction": fraction,
            **props(phase),
            "mole_fractions": {
                by_name[str(n)]: _num(phase.Compounds[n].MoleFraction)
                for n in phase.Compounds.Keys
                if str(n) in by_name
            },
        }
    found = {
        **props(mixture),
        "molar_mass_kg_kmol": _num(mixture.Properties.molecularWeight),
        "phases": phases,
    }
    q = (feed or {}).get("vapor_fraction")
    if q is not None and float(q) in INCIPIENT:
        index, name = INCIPIENT[float(q)]
        phase = obj.Phases[index]
        found["incipient"] = {
            "phase": name,
            "mole_fractions": {
                by_name[str(n)]: _num(phase.Compounds[n].MoleFraction)
                for n in phase.Compounds.Keys
                if str(n) in by_name
            },
        }
    return found


#: The parameters of an NRTL or UNIQUAC pair entry (UNIQUAC has no alpha12).
ACTIVITY_PARAMETERS = ("A12", "A21", "B12", "B21", "C12", "C21", "alpha12")
#: The settings of an activity-coefficient package that change its phase equilibrium or
#: parameters (reported for NRTL and UNIQUAC only).
ACTIVITY_SETTINGS = (
    "VaporPhaseFugacityCalculationMode",
    "LiquidFugacity_UsePoyntingCorrectionFactor",
    "AutoEstimateMissingNRTLUNIQUACParameters",
    "ActivityCoefficientModels_IgnoreMissingInteractionParameters",
)


def _package(pp: Any, names: dict[str, str]) -> dict[str, Any]:
    """The binary interaction parameters the package holds for the model's compounds (each pair
    once, as DWSIM stores it): the equation-of-state ``kij`` (None where it holds none) and,
    for NRTL and UNIQUAC, ``activity``, the pair's entry (``components`` in the order DWSIM
    stores it, component 1 first; None where it holds none). Also its liquid-density settings
    and, for NRTL and UNIQUAC, :data:`ACTIVITY_SETTINGS`."""
    pairs = []
    table = getattr(getattr(pp, "m_pr", None), "InteractionParameters", None)
    activity = getattr(getattr(pp, "m_uni", None), "InteractionParameters", None)
    ids = list(names)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            pair: dict[str, Any] = {"components": [a, b], "kij": None}
            for p, q in ((names[a], names[b]), (names[b], names[a])):
                if table is not None and table.ContainsKey(p) and table[p].ContainsKey(q):
                    pair["kij"] = _num(table[p][q].kij)
                    break
            if activity is not None:
                pair["activity"] = None
                for (p, q), order in (
                    ((names[a], names[b]), [a, b]),
                    ((names[b], names[a]), [b, a]),
                ):
                    if activity.ContainsKey(p) and activity[p].ContainsKey(q):
                        entry = activity[p][q]
                        pair["activity"] = {
                            "components": order,
                            **{
                                k: _num(getattr(entry, k))
                                for k in ACTIVITY_PARAMETERS
                                if hasattr(entry, k)
                            },
                        }
                        break
            pairs.append(pair)
    settings = {}
    keys = [
        "LiquidDensityCalculationMode_Subcritical",
        "LiquidDensityCalculationMode_Supercritical",
        "LiquidDensity_UsePenelouxVolumeTranslation",
        "LiquidDensity_CorrectExpDataForPressure",
    ]
    if activity is not None:
        keys += ACTIVITY_SETTINGS
    for key in keys:
        value = getattr(pp, key, None)
        if value is not None:
            settings[key] = str(value)
    return {"interaction_parameters": pairs, "package_settings": settings}


def _compound_data(automation: Any, names: dict[str, str]) -> dict[str, Any]:
    """Compound id -> DWSIM's own ideal-gas formation enthalpy at 298.15 K (kJ/kmol, from its
    kJ/kg times its molar mass) and molar mass, with the database they come from: what its
    reactors take for the heat of reaction (the energy audit compares them with the declared
    values)."""
    found = {}
    available = automation.AvailableCompounds
    for cid, name in names.items():
        try:
            c = available[name]
            mw = _num(c.Molar_Weight)
            hf = _num(c.IG_Enthalpy_of_Formation_25C)
            found[cid] = {
                "dHf_298_kJ_kmol": hf * mw if hf is not None and mw is not None else None,
                "molar_mass": mw,
                "database": str(getattr(c, "OriginalDB", "") or ""),
            }
        except Exception:  # noqa: BLE001 - the results stand without the constants
            found[cid] = {"dHf_298_kJ_kmol": None, "molar_mass": None, "database": ""}
    return found


def _version(text: str) -> str:
    """``9.0.5.0`` from ``DWSIM version 9.0.5.0 (10/02/2025 23:49:46)``."""
    found = re.search(r"\d+(?:\.\d+)+", text)
    return found.group(0) if found else text


def _abs(value: Any) -> float | None:
    """A column duty as a magnitude: DWSIM's sign differs between the column models."""
    found = _num(value)
    return abs(found) if found is not None else None


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _specify(unit: Any, u: dict[str, Any], unitops: Any, names: dict[str, str]) -> None:
    spec = u["spec"]
    kind = u["type"]
    if kind in ("compressor", "pump"):
        modes = (unitops.Compressor if kind == "compressor" else unitops.Pump).CalculationMode
        if "pressure_ratio" in spec:
            unit.CalcMode = modes.PressureRatio
            unit.PressureRatio = spec["pressure_ratio"]
        elif "outlet_pressure_Pa" in spec:
            unit.CalcMode = modes.OutletPressure
            if kind == "compressor":
                unit.POut = spec["outlet_pressure_Pa"]
            else:
                unit.Pout = spec["outlet_pressure_Pa"]
        else:
            unit.CalcMode = modes.Delta_P
            unit.PressureIncrease = spec["pressure_increase_Pa"]
            unit.DeltaP = spec["pressure_increase_Pa"]
        if kind == "compressor":
            unit.AdiabaticEfficiency = 100.0 * spec["efficiency"]
        else:
            unit.Eficiencia = 100.0 * spec["efficiency"]
    elif kind == "expander":
        modes = unitops.Expander.CalculationMode
        if "outlet_pressure_Pa" in spec:
            unit.CalcMode = modes.OutletPressure
            unit.POut = spec["outlet_pressure_Pa"]
        else:
            unit.CalcMode = modes.Delta_P
            unit.PressureDrop = spec["pressure_drop_Pa"]
            unit.DeltaP = spec["pressure_drop_Pa"]
        unit.AdiabaticEfficiency = 100.0 * spec["efficiency"]
    elif kind in ("heater", "cooler"):
        modes = (unitops.Heater if kind == "heater" else unitops.Cooler).CalculationMode
        if "outlet_temperature_K" in spec:
            unit.CalcMode = modes.OutletTemperature
            unit.OutletTemperature = spec["outlet_temperature_K"]
        elif kind == "heater":
            unit.CalcMode = modes.HeatAdded
            unit.DeltaQ = spec["duty_kW"]
        else:
            unit.CalcMode = modes.HeatRemoved
            unit.DeltaQ = -spec["duty_kW"]
        unit.DeltaP = spec.get("pressure_drop_Pa", 0.0)
    elif kind == "valve":
        modes = unitops.Valve.CalculationMode
        if "outlet_pressure_Pa" in spec:
            unit.CalcMode = modes.OutletPressure
            unit.OutletPressure = spec["outlet_pressure_Pa"]
        else:
            unit.CalcMode = modes.DeltaP
            unit.DeltaP = spec["pressure_drop_Pa"]
    elif kind == "mixer":
        unit.PressureCalculation = unitops.Mixer.PressureBehavior.Minimum
    elif kind == "splitter":
        unit.OperationMode = unitops.Splitter.OpMode.SplitRatios
        # one ratio per outlet port of the splitter (three), unconnected ones zero
        ratios = unit.Ratios
        fractions = [float(v) for v in spec["fractions"]]
        while ratios.Count < len(fractions):
            ratios.Add(0.0)
        for k in range(ratios.Count):
            ratios[k] = fractions[k] if k < len(fractions) else 0.0
    elif kind == "flash":
        # without an override the vessel flashes at the inlet conditions (adiabatic); with one
        # it holds that temperature or pressure and the duty follows
        unit.PressureCalculation = unitops.Vessel.PressureBehavior.Minimum
        if "temperature_K" in spec:
            unit.OverrideT = True
            unit.FlashTemperature = spec["temperature_K"]
        if "pressure_Pa" in spec:
            unit.OverrideP = True
            unit.FlashPressure = spec["pressure_Pa"]
    elif kind == "heat_exchanger":
        modes = unitops.HeatExchangerCalcMode
        if "hot_outlet_temperature_K" in spec:
            unit.CalculationMode = modes.CalcTempColdOut
            unit.HotSideOutletTemperature = spec["hot_outlet_temperature_K"]
        elif "cold_outlet_temperature_K" in spec:
            unit.CalculationMode = modes.CalcTempHotOut
            unit.ColdSideOutletTemperature = spec["cold_outlet_temperature_K"]
        else:
            unit.CalculationMode = modes.CalcBothTemp
            unit.Q = spec["duty_kW"]
        unit.HotSidePressureDrop = spec.get("hot_pressure_drop_Pa", 0.0)
        unit.ColdSidePressureDrop = spec.get("cold_pressure_drop_Pa", 0.0)
    elif kind in REACTORS:
        import DWSIM.UnitOperations.Reactors as reactors
        from System import Double, String
        from System.Collections.Generic import List

        modes = reactors.OperationMode
        mode = spec["mode"]
        unit.ReactorOperationMode = {
            "isothermal": modes.Isothermic,
            "adiabatic": modes.Adiabatic,
            "outlet_temperature": modes.OutletTemperature,
        }[mode]
        if mode == "outlet_temperature":
            unit.OutletTemperature = spec["outlet_temperature_K"]
        unit.DeltaP = spec.get("pressure_drop_Pa", 0.0)
        if kind == "gibbs_reactor":
            ids = List[String]()
            for cid in spec["components"]:
                ids.Add(names[cid])
            unit.ComponentIDs = ids
            unit.CreateElementMatrix()
            # any positive start converges (the minimum is unique); DWSIM refuses none
            estimates = List[Double]()
            for _ in spec["components"]:
                estimates.Add(1.0)
            unit.InitialEstimates = estimates
    elif kind == "component_separator":
        from DWSIM.UnitOperations.UnitOperations.Auxiliary import (
            ComponentSeparationSpec,
            SeparationSpec,
        )

        specs = unit.ComponentSepSpecs
        for cid, name in names.items():
            entry = ComponentSeparationSpec()
            entry.ComponentID = name
            entry.SepSpec = SeparationSpec.PercentInletMolarFlow
            entry.SpecValue = 100.0 * float(spec["recoveries"].get(cid, 0.0))
            entry.SpecUnit = "%"
            if specs.ContainsKey(name):
                specs[name] = entry
            else:
                specs.Add(name, entry)
        unit.SpecifiedStreamIndex = int(spec["recovery_outlet"])
    elif kind == "distillation_column":
        types = unitops.Column.condtype
        unit.SetTopPressure(spec["condenser_pressure_Pa"])
        unit.ColumnPressureDrop = spec["reboiler_pressure_Pa"] - spec["condenser_pressure_Pa"]
        unit.MaxIterations = 300
        unit.InternalLoopTolerance = COLUMN_TOLERANCE
        unit.ExternalLoopTolerance = COLUMN_TOLERANCE
        unit.AutoUpdateInitialEstimates = True
        unit.CondenserType = {
            "total": types.Total_Condenser,
            "partial": types.Partial_Condenser,
            "none": types.Full_Reflux,
        }[spec["condenser"]]
        if spec["condenser"] == "none":
            unit.SetCondenserSpec("Stream_Ratio", REFLUX_STEPS[0], "", "")
        else:
            s = spec["condenser_spec"]
            compound = names.get(s["component"], "") if s.get("component") else ""
            unit.SetCondenserSpec(s["type"], float(s["value"]), s["unit"], compound)
        if spec["reboiler"]:
            s = spec["reboiler_spec"]
            compound = names.get(s["component"], "") if s.get("component") else ""
            unit.SetReboilerSpec(s["type"], float(s["value"]), s["unit"], compound)
        else:
            unit.SetReboilerSpec("Heat_Duty", 0.0, "kW", "")
        if spec.get("vapor_flow"):
            unit.VaporFlowRate = _kmol_h(spec["vapor_flow"], spec["mw_guess"])
            unit.VaporFlowRateUnit = "kmol/h"
    elif kind == "shortcut_column":
        unit.m_lightkey = names[spec["light_key"]]
        unit.m_heavykey = names[spec["heavy_key"]]
        unit.m_lightkeymolarfrac = spec["light_key_in_bottoms"]
        unit.m_heavykeymolarfrac = spec["heavy_key_in_distillate"]
        unit.m_refluxratio = spec["reflux_ratio"]
        unit.m_condenserpressure = spec["condenser_pressure_Pa"]
        unit.m_boilerpressure = spec["reboiler_pressure_Pa"]
        types = unitops.ShortcutColumn.CondenserType
        unit.CondenserType = types.TotalCond if spec["condenser"] == "total" else types.PartialCond


def main() -> int:
    out = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)  # whatever DWSIM prints goes to stderr; stdout carries the result only
    try:
        result = solve(json.loads(sys.stdin.read()))
    except Exception as failure:  # noqa: BLE001 - reported to cheme-as-code, which raises
        result = {"ok": False, "error": f"{type(failure).__name__}: {failure}"}
    out.write(json.dumps(result) + "\n")
    out.flush()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
