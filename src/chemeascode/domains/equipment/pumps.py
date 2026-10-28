"""Pump sizing from explicit inputs: the public API behind ``cheme datasheets fill``'s pumps.

``cheme datasheets fill`` sizes a pump from the flowsheet streams it is linked to. A pump the
flowsheet does not link (one that draws from a battery limit, a utility pump) is sized here
from what the caller states: the end points of its suction and discharge lines in the layout
model, the fluid state and the flow. The lines are the routed pipes of
``layout/plant-model.yaml``; their losses are Darcy-Weisbach with the Colebrook friction factor
and the fitting K of the package table (:mod:`chemeascode.domains.process.hydraulics`).

An end point is

- ``TAG``: any nozzle of item *TAG* (the nearest along the routed pipes);
- ``TAG/N2``: that nozzle;
- ``pipe:<pipe id>:start`` or ``pipe:<pipe id>:end``: an end of a routed pipe, by the pipe's id
  in the layout model: a free end (a battery limit) or a tie-in where it meets another pipe. The
  line stops there; naming it changes nothing in the network, so a :class:`PipeNetwork` sizes
  any number of pumps in any order. An end on an item nozzle is that nozzle.

Every result carries its basis text (the pipes, schedules, roughness, fittings and their
sources) and whether an input was an assumption. Units are SI, pressures kPa(a)::

    from chemeascode.domains.equipment import pumps

    net = pumps.network(model)  # the parsed layout/plant-model.yaml
    duty = pumps.size_pump(
        net, "P-1101A",
        suction_from="pipe:P-01/Line_CW1001_S1:start", discharge_to="C-1101",
        mass_flow_kg_s=69.25, density_kg_m3=997.0, viscosity_pa_s=0.89e-3,
        suction_pressure_kpa=501.3, discharge_pressure_kpa=580.0,
        vapour_pressure_kpa=3.17, efficiency=0.75, allowance_kpa=100.0,
    )
    duty.differential_head_m, duty.npsh_available_m, duty.shaft_power_kw
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.equipment import sizing
from chemeascode.domains.equipment.fill import Param, _Network, _Refused, _route
from chemeascode.domains.process.hydraulics import G
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE


class SizingError(ValueError):
    """A line or duty cannot be calculated from the inputs; the message says why."""


class PipeNetwork:
    """The routed pipes of a layout model as a network (build it once, size many pumps)."""

    def __init__(self, model: dict[str, Any]) -> None:
        self._network = _Network(model)

    @classmethod
    def _of(cls, built: _Network) -> PipeNetwork:
        """A network around one the fill already built (its labelled ends kept)."""
        net = cls.__new__(cls)
        net._network = built
        return net

    def endpoint(self, spec: str) -> str:
        """The network label of end point *spec* (see the module text)."""
        spec = spec.strip()
        if spec.startswith("pipe:"):
            body = spec[len("pipe:") :]
            pipe_id, _, end = body.rpartition(":")
            ref = self._network.open_end(pipe_id, end)
            if ref is None:
                raise SizingError(
                    f"{spec}: no routed pipe {pipe_id!r} in the layout model, or the end is "
                    "not start or end"
                )
            return ref
        return spec


def network(model: dict[str, Any] | PipeNetwork | Path | str) -> PipeNetwork:
    """A :class:`PipeNetwork` of *model*: the parsed layout model, a plant root (its
    ``layout/plant-model.yaml``), or a network already built."""
    if isinstance(model, PipeNetwork):
        return model
    if isinstance(model, Path | str):
        path = Path(model)
        if path.is_dir():
            path = path / LAYOUT_MODEL_FILE
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise SizingError(f"{path}: not a layout model")
        model = loaded
    return PipeNetwork(model)


@dataclass(frozen=True)
class Line:
    """One routed line of a pump: from the pump's nozzle to the end point reached."""

    pump_nozzle: str
    end: str
    head_loss_m: float
    pressure_drop_kpa: float
    elevation_pump_m: float
    elevation_end_m: float
    basis: str
    assumed: bool
    #: What the line's losses read, as a filled value's inputs (``pipe:<id>``,
    #: ``nozzle:<TAG>/<N>``, ``table:<table>/<row>``; see ``fill.input_data``).
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PumpDuty:
    """The duty of a pump from explicit inputs (see :func:`size_pump`); ``basis`` holds the
    calculation of each value, ``assumed`` whether any input was an assumption."""

    flow_m3_h: float
    differential_head_m: float
    npsh_available_m: float | None
    shaft_power_kw: float | None
    suction: Line
    discharge: Line
    basis: dict[str, str]
    assumed: bool


class _Stub:
    """What the fill's router asks of a datasheet: its tag and declared parameters."""

    def __init__(self, tag: str, params: dict[str, Param]) -> None:
        self.tag, self.params = tag, params

    def param(self, name: str) -> Param | None:
        return self.params.get(name)


class _Ctx:
    def __init__(self, net: Any) -> None:
        self.network = net


def _params(
    nozzle_name: str | None,
    nozzle: str | None,
    schedule: str | None,
    roughness: str | None,
    assumed: bool,
) -> dict[str, Param]:
    params: dict[str, Param] = {}
    if nozzle and nozzle_name:
        params[nozzle_name] = Param(nozzle, "the caller", False)
    if schedule:
        params["pipe_schedule"] = Param(schedule, "the caller", assumed)
    if roughness:
        params["pipe_roughness"] = Param(roughness, "the caller", assumed)
    return params


def route_line(
    model: dict[str, Any] | PipeNetwork | Path | str,
    pump: str,
    to: str,
    *,
    mass_flow_kg_s: float,
    density_kg_m3: float,
    viscosity_pa_s: float,
    nozzle: str | None = None,
    exclude_nozzle: str | None = None,
    schedule: str | None = None,
    roughness: str | None = None,
    inputs_assumed: bool = True,
    what: str = "suction",
) -> Line:
    """The routed line from a nozzle of *pump* (*nozzle*, e.g. ``N1``, else the nearest one
    that is not *exclude_nozzle* ``TAG/N``) to end point *to*, and its losses. *schedule*
    (``40``, ``10S``; default 40, ASSUMED) and *roughness* (a row of the roughness table;
    default commercial steel for a steel pipe class, ASSUMED) apply to every pipe of it;
    *inputs_assumed* marks a given schedule or roughness as an assumption."""
    net = network(model)
    target = net.endpoint(to)
    stub = _Stub(pump, _params("nozzle", nozzle, schedule, roughness, inputs_assumed))
    try:
        found = _route(
            stub,  # type: ignore[arg-type]
            _Ctx(net._network),  # type: ignore[arg-type]
            "nozzle",
            [target],
            exclude_nozzle,
            mass_flow_kg_s,
            density_kg_m3,
            viscosity_pa_s,
            what,
        )
    except _Refused as refusal:
        raise SizingError(refusal.reason) from refusal
    return Line(
        found.nozzle,
        found.target,
        found.loss.head,
        found.loss.pressure_drop,
        found.elevation_pump,
        found.elevation_target,
        found.text,
        found.assumed,
        tuple(found.inputs),
    )


def size_pump(
    model: dict[str, Any] | PipeNetwork | Path | str,
    pump: str,
    *,
    suction_from: str,
    discharge_to: str,
    mass_flow_kg_s: float,
    density_kg_m3: float,
    viscosity_pa_s: float,
    suction_pressure_kpa: float,
    discharge_pressure_kpa: float,
    vapour_pressure_kpa: float | None = None,
    efficiency: float | None = None,
    allowance_kpa: float = 0.0,
    suction_nozzle: str | None = None,
    discharge_nozzle: str | None = None,
    schedule: str | None = None,
    roughness: str | None = None,
    inputs_assumed: bool = True,
) -> PumpDuty:
    """Size *pump* between end points *suction_from* and *discharge_to* (see the module text).

    The pressures apply at the end points (the source's and the destination's nozzle or the
    pipe end), not at the pump: the head is ``(p_d - p_s) / (rho g)`` plus the static head
    between the two end points plus the routed line losses plus *allowance_kpa* (a control
    valve, strainer, distributor). NPSH available is ``(p_s - p_vap) / (rho g)`` plus the
    height of the suction end point over the pump's suction nozzle less the suction losses
    (no liquid level counted); without *vapour_pressure_kpa* it is None. The shaft power is
    ``m g H / efficiency`` (None without an efficiency)."""
    net = network(model)
    common = {
        "mass_flow_kg_s": mass_flow_kg_s,
        "density_kg_m3": density_kg_m3,
        "viscosity_pa_s": viscosity_pa_s,
        "schedule": schedule,
        "roughness": roughness,
        "inputs_assumed": inputs_assumed,
    }
    suction = route_line(net, pump, suction_from, nozzle=suction_nozzle, what="suction", **common)
    discharge = route_line(
        net,
        pump,
        discharge_to,
        nozzle=discharge_nozzle,
        exclude_nozzle=suction.pump_nozzle,
        what="discharge",
        **common,
    )
    rho = density_kg_m3
    pressure = sizing.pressure_head(discharge_pressure_kpa - suction_pressure_kpa, rho)
    static = discharge.elevation_end_m - suction.elevation_end_m
    extra = sizing.pressure_head(allowance_kpa, rho) if allowance_kpa else 0.0
    head = pressure + static + suction.head_loss_m + discharge.head_loss_m + extra
    flow = mass_flow_kg_s / rho * 3600.0
    basis = {
        "flow_m3_h": f"Q = m / rho = {mass_flow_kg_s * 3600:.6g} kg/h / {rho:.5g} kg/m3",
        "differential_head_m": (
            f"H = ({discharge_pressure_kpa:.5g} - {suction_pressure_kpa:.5g}) kPa / (rho g) "
            f"{pressure:.4g} m + static {static:.4g} m ({discharge.end} at z "
            f"{discharge.elevation_end_m:.3f} m - {suction.end} at z "
            f"{suction.elevation_end_m:.3f} m, {LAYOUT_MODEL_FILE}; liquid levels not counted)"
            f" + suction losses {suction.head_loss_m:.4g} m + discharge losses "
            f"{discharge.head_loss_m:.4g} m"
            + (f" + allowance {allowance_kpa:g} kPa {extra:.4g} m" if allowance_kpa else "")
            + f" = {head:.4g} m; {suction.basis}; {discharge.basis}"
        ),
    }
    npsh = None
    if vapour_pressure_kpa is not None:
        static_s = suction.elevation_end_m - suction.elevation_pump_m
        npsh = sizing.npsh_available(
            suction_pressure_kpa, vapour_pressure_kpa, rho, static_s, suction.head_loss_m
        )
        basis["npsh_available_m"] = (
            f"NPSHa = ({suction_pressure_kpa:.5g} - {vapour_pressure_kpa:.4g}) kPa / (rho g) + "
            f"static {static_s:.4g} m ({suction.end} at z {suction.elevation_end_m:.3f} m above "
            f"suction {suction.pump_nozzle} at z {suction.elevation_pump_m:.3f} m; no liquid "
            f"level counted) - suction losses {suction.head_loss_m:.4g} m = {npsh:.4g} m"
        )
    power = None
    if efficiency is not None:
        if efficiency <= 0:
            raise SizingError(f"efficiency {efficiency:g} is not positive")
        power = sizing.hydraulic_power(mass_flow_kg_s, head) / efficiency
        basis["shaft_power_kw"] = (
            f"P = m g H / eta = {mass_flow_kg_s:.4g} kg/s x {G} m/s2 x {head:.4g} m / "
            f"{efficiency:g} = {power:.4g} kW"
        )
    return PumpDuty(
        flow,
        head,
        npsh,
        power,
        suction,
        discharge,
        basis,
        inputs_assumed or suction.assumed or discharge.assumed,
    )
