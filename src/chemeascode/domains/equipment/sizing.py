"""Equipment sizing calculations: typed, working-directory independent, SI or stated units.

`cheme datasheets fill` (:mod:`chemeascode.domains.equipment.fill`) applies them to the
draft datasheets; they are usable on their own with explicit inputs.

- Heat exchangers: log-mean temperature difference for counter- and co-current flow, the
  correction factor F of one shell pass and an even number of tube passes (Bowman, Mueller and
  Nagle 1940), ``A = Q / (U F LMTD)`` times a margin, and the typical overall coefficients of
  ``data/overall-coefficients.yaml`` (Sinnott 2005, Table 12.1).
- Pumps: differential head from the pressures, static head and losses; hydraulic and shaft
  power; NPSH available.
- Compressors and expanders: the number of stages for a maximum pressure ratio per stage, and
  ideal-gas isentropic or polytropic power (the real-gas route through the property adapter is
  in :mod:`chemeascode.domains.equipment.fill`).
- Vessels: the volume of a cylinder and a residence time.

This is preliminary process sizing. Equipment-specific rating, mechanical design to a code,
material and corrosion allowance selection, relief sizing and dynamics are not calculated
anywhere in core: :mod:`chemeascode.domains.equipment.coverage` declares the status per class
and aspect (docs/framework/sizing.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.process.hydraulics import G

U_TABLE = Path(__file__).parent / "data" / "overall-coefficients.yaml"
#: Universal gas constant, kJ/(kmol K) (CODATA 2018).
R = 8.314462618
BOWMAN = (
    "Bowman, Mueller and Nagle, Mean temperature difference in design, Trans. ASME 62 (1940) "
    "283-294"
)
#: Flow arrangements :func:`correction_factor` knows.
ARRANGEMENTS = ("counter-current", "co-current", "1-2")
#: Below this F a single 1-2 shell is not a sound design: F falls steeply there and a small
#: error in the temperatures changes the area a lot; more shells in series are used instead.
F_MIN = 0.75
F_MIN_SOURCE = (
    "the usual design limit F >= 0.75 (R. K. Sinnott, Coulson & Richardson's Chemical "
    "Engineering Vol. 6, 4th ed. (2005), Section 12.6; D. Q. Kern, Process Heat Transfer (1950))"
)


# -- heat exchangers ------------------------------------------------------------------------------


def lmtd(hot_in: float, hot_out: float, cold_in: float, cold_out: float, arrangement: str) -> float:
    """Log-mean temperature difference (K) for *arrangement*: ``co-current`` pairs the inlets,
    every other arrangement takes the counter-current LMTD (F corrects it)."""
    if arrangement == "co-current":
        d1, d2 = hot_in - cold_in, hot_out - cold_out
    else:
        d1, d2 = hot_in - cold_out, hot_out - cold_in
    if d1 <= 0 or d2 <= 0:
        raise ValueError(
            f"temperature cross: terminal differences {d1:.3g} K and {d2:.3g} K for "
            f"{arrangement} flow"
        )
    if abs(d1 - d2) < 1e-9 * max(d1, d2):
        return d1
    return (d1 - d2) / math.log(d1 / d2)


def correction_factor(
    hot_in: float, hot_out: float, cold_in: float, cold_out: float, arrangement: str
) -> float:
    """LMTD correction factor F: 1 for pure counter- or co-current flow; for ``1-2`` (one
    shell pass, an even number of tube passes) the equation of Bowman, Mueller and Nagle."""
    if arrangement in ("counter-current", "co-current"):
        return 1.0
    if arrangement != "1-2":
        raise ValueError(f"unknown arrangement {arrangement!r}: one of {', '.join(ARRANGEMENTS)}")
    r = (hot_in - hot_out) / (cold_out - cold_in)
    p = (cold_out - cold_in) / (hot_in - cold_in)
    s = math.sqrt(r * r + 1.0)
    if abs(r - 1.0) < 1e-9:
        num = p * math.sqrt(2.0) / (1.0 - p)
        den = math.log((2.0 - p * (2.0 - math.sqrt(2.0))) / (2.0 - p * (2.0 + math.sqrt(2.0))))
        f = num / den
    else:
        a = (2.0 - p * (r + 1.0 - s)) / (2.0 - p * (r + 1.0 + s))
        b = (1.0 - p) / (1.0 - p * r)
        if a <= 0 or b <= 0:
            raise ValueError("no 1-2 exchanger reaches these temperatures (F undefined)")
        f = s * math.log(b) / ((r - 1.0) * math.log(a))
    if not 0.0 < f <= 1.0 + 1e-9 or math.isnan(f):
        raise ValueError("no 1-2 exchanger reaches these temperatures (F undefined)")
    return f


def exchanger_area(duty_kw: float, u: float, f: float, lmtd_k: float, margin: float = 0.0) -> float:
    """Heat-transfer area, m2: ``Q / (U F LMTD) (1 + margin)``; Q kW, U W/(m2 K)."""
    return abs(duty_kw) * 1000.0 / (u * f * lmtd_k) * (1.0 + margin)


@cache
def _u_table() -> dict[str, Any]:
    return yaml.safe_load(U_TABLE.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class TypicalU:
    """A row of the typical overall coefficients: the design typical (the middle of its
    range, ASSUMED), the range, and the source."""

    id: str
    value: float
    low: float
    high: float
    source: str


def typical_u(row: str) -> TypicalU | None:
    """The typical overall coefficient of row *row* (``cooler/gases-water``), W/(m2 K)."""
    table = _u_table()
    entry = table["rows"].get(row)
    if entry is None:
        return None
    low, high = (float(v) for v in entry["range"])
    title = f"{entry['exchanger']}, {entry['hot']} / {entry['cold']}"
    return TypicalU(row, (low + high) / 2.0, low, high, f"{table['source']}: {title}")


def u_rows() -> list[str]:
    return sorted(_u_table()["rows"])


def u_row(row: str) -> dict[str, Any] | None:
    """Row *row* of the typical overall coefficients as the table states it (without its
    verification note ``check``), for the fingerprint of a value that used it."""
    entry = _u_table()["rows"].get(row)
    return {k: v for k, v in entry.items() if k != "check"} if entry is not None else None


# -- pumps ----------------------------------------------------------------------------------------


def pressure_head(dp_kpa: float, density: float) -> float:
    """Head of a pressure difference, m of liquid; kPa, kg/m3."""
    return dp_kpa * 1000.0 / (density * G)


def hydraulic_power(mass_flow: float, head: float) -> float:
    """Power given to the liquid, kW: ``m g H``; kg/s, m."""
    return mass_flow * G * head / 1000.0


def npsh_available(
    source_pressure_kpa: float,
    vapour_pressure_kpa: float,
    density: float,
    static_head: float,
    suction_loss: float,
) -> float:
    """NPSH available at the pump suction, m: ``(p_source - p_vap) / (rho g) + static head -
    suction losses``; absolute pressures in kPa, static head from the source level (or nozzle)
    down to the pump suction, m."""
    return (
        pressure_head(source_pressure_kpa - vapour_pressure_kpa, density)
        + static_head
        - suction_loss
    )


# -- compressors and expanders --------------------------------------------------------------------


def stages_for(pressure_ratio: float, max_stage_ratio: float) -> tuple[int, float]:
    """The number of stages for an overall *pressure_ratio* when no stage exceeds
    *max_stage_ratio*, and the (equal) ratio per stage."""
    if max_stage_ratio <= 1.0:
        raise ValueError("the maximum pressure ratio per stage must exceed 1")
    if pressure_ratio <= 1.0:
        return 1, pressure_ratio
    n = max(1, math.ceil(math.log(pressure_ratio) / math.log(max_stage_ratio) - 1e-12))
    return n, pressure_ratio ** (1.0 / n)


@dataclass
class IdealGasStage:
    """One ideal-gas compression (or expansion) stage: specific work kJ/kg (positive into the
    gas) and the outlet temperature K."""

    work: float
    outlet_temperature: float


def ideal_gas_stage(
    inlet_temperature: float,
    pressure_ratio: float,
    k: float,
    molar_mass: float,
    efficiency: float,
    kind: str = "isentropic",
    z: float = 1.0,
) -> IdealGasStage:
    """Ideal-gas stage with constant heat-capacity ratio *k*: for compression
    (*pressure_ratio* > 1) the work is the isentropic work over the isentropic efficiency; for
    expansion (ratio < 1) the isentropic work times the efficiency. Polytropic: the gas work
    ``cp T1 (r^((n - 1)/n) - 1)`` with ``(n - 1)/n = (k - 1)/(k eta_p)`` for compression and
    ``(k - 1) eta_p / k`` for expansion (the polytropic head is eta_p times this work in
    compression). kJ/kg, K; *molar_mass* kg/kmol."""
    rt = z * R * inlet_temperature / molar_mass  # kJ/kg
    m = (k - 1.0) / k
    compression = pressure_ratio >= 1.0
    if kind == "polytropic":
        n = m / efficiency if compression else m * efficiency
        work = rt / m * (pressure_ratio**n - 1.0)  # cp T1 (r^n - 1)
    elif kind == "isentropic":
        ideal = rt / m * (pressure_ratio**m - 1.0)
        work = ideal / efficiency if compression else ideal * efficiency
    else:
        raise ValueError(f"unknown kind {kind!r}: isentropic or polytropic")
    cp = z * R * k / ((k - 1.0) * molar_mass)  # kJ/(kg K)
    return IdealGasStage(work, inlet_temperature + work / cp)


# -- vessels --------------------------------------------------------------------------------------


def cylinder_volume(diameter: float, length: float) -> float:
    """Volume of a cylinder, m3 (heads not counted)."""
    return math.pi / 4.0 * diameter**2 * length


def residence_time_min(volume_m3: float, volume_flow_m3_h: float) -> float:
    """Residence time of *volume_flow_m3_h* in *volume_m3*, minutes."""
    return volume_m3 / volume_flow_m3_h * 60.0
