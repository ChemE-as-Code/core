"""Single-phase line losses: Darcy-Weisbach with the Colebrook friction factor.

Typed, working-directory independent functions with SI inputs. The package data
(``data/hydraulics.yaml``) holds the pipe roughness (Moody 1944), the fitting resistance
coefficients (Perry's 7th ed., Table 6-4) and the outside diameter and wall thickness by
schedule (ASME B36.10M / B36.19M); every value returned from it carries its source.

- Reynolds number ``Re = rho v D / mu``.
- Laminar (``Re < 2000``): ``f = 64 / Re``.
- Turbulent: Colebrook (1939), ``1/sqrt(f) = -2 log10(e/(3.7 D) + 2.51/(Re sqrt(f)))``, solved by
  fixed-point iteration from the explicit Swamee-Jain (1976) approximation
  ``f = 0.25 / log10(e/(3.7 D) + 5.74/Re^0.9)^2``. Between 2000 and 4000 the flow is
  transitional and the result says so.
- Head loss ``h = (f L / D + sum K) v^2 / (2 g)``.

References: C. F. Colebrook, J. Inst. Civil Eng. 11 (1939) 133-156; P. K. Swamee, A. K. Jain,
J. Hydraulics Div. ASCE 102 (1976) 657-664.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

DATA = Path(__file__).parent / "data" / "hydraulics.yaml"
#: Standard acceleration of gravity, m/s2 (CGPM 1901).
G = 9.80665
LAMINAR_RE = 2000.0
TURBULENT_RE = 4000.0


@cache
def _data() -> dict[str, Any]:
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Sourced:
    """A value from the package tables with its source."""

    value: float
    source: str


def roughness(material: str) -> Sourced | None:
    """Absolute roughness of *material* (a row id of the roughness table), m."""
    table = _data()["roughness"]
    row = table["rows"].get(material)
    if row is None:
        return None
    return Sourced(float(row["mm"]) / 1000.0, f"{table['source']}: {row['title']}")


def roughness_materials() -> list[str]:
    return sorted(_data()["roughness"]["rows"])


def fitting_k(kind: str) -> Sourced | None:
    """Resistance coefficient of fitting *kind* (``elbow_90``, ``GlobeValve``, ...)."""
    table = _data()["fittings"]
    row = table["rows"].get(kind)
    if row is None:
        return None
    return Sourced(float(row["k"]), f"{table['source']}: {row['title']}")


def wall_thickness(dn: float, schedule: str) -> Sourced | None:
    """Wall thickness of a DN *dn* pipe of *schedule* (``40``, ``10S``), m."""
    table = _data()["walls"]
    rows = table["schedules"].get(str(schedule))
    if rows is None:
        return None
    for size, mm in rows.items():
        if abs(float(size) - dn) < 1e-6:
            return Sourced(float(mm) / 1000.0, f"{table['source']}: schedule {schedule}, DN {size}")
    return None


def outside_diameter(dn: float) -> Sourced | None:
    """ASME B36.10M / B36.19M outside diameter of DN *dn*, m (the OD a schedule's wall
    belongs to)."""
    table = _data()["walls"]
    for size, mm in table["od_mm"].items():
        if abs(float(size) - dn) < 1e-6:
            return Sourced(float(mm) / 1000.0, f"{table['od_source']}: DN {size}")
    return None


def table_row(table: str, row: str) -> dict[str, Any] | None:
    """Row *row* of the ``roughness`` or ``fittings`` table as it stands (without its
    verification note ``check``), for the fingerprint of a value that used it."""
    found = (_data().get(table) or {}).get("rows", {}).get(row)
    return {k: v for k, v in found.items() if k != "check"} if isinstance(found, dict) else None


def size_row(dn: float, schedule: str) -> dict[str, Any] | None:
    """The outside diameter and the *schedule* wall of DN *dn*, mm, as the tables state them (what
    :func:`inside_diameter` reads), for the fingerprint of a value that used them."""
    table = _data()["walls"]
    od = next((mm for s, mm in table["od_mm"].items() if abs(float(s) - dn) < 1e-6), None)
    rows = table["schedules"].get(str(schedule)) or {}
    wall = next((mm for s, mm in rows.items() if abs(float(s) - dn) < 1e-6), None)
    return None if od is None and wall is None else {"od_mm": od, "wall_mm": wall}


def inside_diameter(dn: float, schedule: str) -> tuple[Sourced, Sourced, Sourced] | None:
    """Inside diameter of a DN *dn* *schedule* pipe, m: the ASME outside diameter less twice
    the schedule's wall. ``(inside, outside, wall)``, or ``None`` when a table has no row."""
    od, wall = outside_diameter(dn), wall_thickness(dn, schedule)
    if od is None or wall is None:
        return None
    inside = od.value - 2.0 * wall.value
    return (
        Sourced(inside, f"OD {od.value * 1000:g} mm - 2 x wall {wall.value * 1000:g} mm"),
        od,
        wall,
    )


def reynolds(density: float, velocity: float, diameter: float, viscosity: float) -> float:
    """Reynolds number; density kg/m3, velocity m/s, diameter m, viscosity Pa s."""
    return density * abs(velocity) * diameter / viscosity


def swamee_jain(re: float, relative_roughness: float) -> float:
    """Darcy friction factor, explicit (Swamee and Jain 1976)."""
    return 0.25 / math.log10(relative_roughness / 3.7 + 5.74 / re**0.9) ** 2


def colebrook(
    re: float, relative_roughness: float, tol: float = 1e-12, max_iter: int = 100
) -> float:
    """Darcy friction factor from the Colebrook equation, iterated from Swamee-Jain."""
    f = swamee_jain(re, relative_roughness)
    for _ in range(max_iter):
        new = (-2.0 * math.log10(relative_roughness / 3.7 + 2.51 / (re * math.sqrt(f)))) ** -2
        if abs(new - f) < tol:
            return new
        f = new
    return f


def friction_factor(re: float, relative_roughness: float) -> tuple[float, str]:
    """Darcy friction factor and the method: laminar, Colebrook, or transitional (Colebrook
    applied between Re 2000 and 4000, where no correlation is reliable)."""
    if re <= 0:
        raise ValueError("Reynolds number must be positive")
    if re < LAMINAR_RE:
        return 64.0 / re, "laminar 64/Re"
    f = colebrook(re, relative_roughness)
    if re < TURBULENT_RE:
        return f, "transitional (Re 2000-4000): Colebrook, uncertain"
    return f, "Colebrook (from Swamee-Jain)"


@dataclass
class Segment:
    """One stretch of pipe: length and inside diameter m, absolute roughness m, and the
    resistance coefficients of its fittings (name -> K, summed)."""

    length: float
    diameter: float
    roughness: float
    fittings: dict[str, float] = field(default_factory=dict)


@dataclass
class SegmentLoss:
    segment: Segment
    velocity: float
    reynolds: float
    friction_factor: float
    method: str
    head: float  # m of liquid


@dataclass
class LineLoss:
    """Head loss of a line of segments in series, m of liquid, and its pressure drop, kPa."""

    head: float
    pressure_drop: float
    segments: list[SegmentLoss]

    def describe(self) -> str:
        parts = []
        for s in self.segments:
            seg = s.segment
            k = sum(seg.fittings.values())
            parts.append(
                f"L {seg.length:.2f} m, ID {seg.diameter * 1000:.1f} mm, v {s.velocity:.2f} m/s, "
                f"Re {s.reynolds:.3g}, f {s.friction_factor:.4f} ({s.method}), sum K {k:g}"
            )
        return "; ".join(parts)


def segment_loss(
    mass_flow: float, density: float, viscosity: float, segment: Segment
) -> SegmentLoss:
    """Darcy-Weisbach head loss of *segment* for *mass_flow* kg/s of a fluid of *density*
    kg/m3 and *viscosity* Pa s."""
    area = math.pi / 4.0 * segment.diameter**2
    velocity = mass_flow / density / area
    re = reynolds(density, velocity, segment.diameter, viscosity)
    f, method = friction_factor(re, segment.roughness / segment.diameter)
    k = sum(segment.fittings.values())
    head = (f * segment.length / segment.diameter + k) * velocity**2 / (2.0 * G)
    return SegmentLoss(segment, velocity, re, f, method, head)


def line_loss(
    mass_flow: float, density: float, viscosity: float, segments: list[Segment]
) -> LineLoss:
    """The head loss (m) and pressure drop (kPa) of *segments* in series."""
    losses = [segment_loss(mass_flow, density, viscosity, s) for s in segments]
    head = sum(s.head for s in losses)
    return LineLoss(head, density * G * head / 1000.0, losses)
