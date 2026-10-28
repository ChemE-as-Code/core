"""Exergy of a stream: chemical plus physical, per kmol, for the dead state 298.15 K, 101.325 kPa.

- **chemical**: ``sum(x_i e_i) + R T0 sum(x_i ln x_i)``, the standard chemical exergies ``e_i`` of
  the components (``data/chemical-exergy.yaml``, Szargut et al. 1988, model II) and the ideal
  mixing term; a stream whose components are not all tabulated has none;
- **physical**: ``(h - h0) - T0 (s - s0)``, the stream's molar enthalpy and entropy against those
  of the same composition at the dead state, from the property method
  (:class:`chemeascode.domains.process.props.Adapter`).

Exergy is the basis of exergy allocation in the LCA: it weighs a compressed or cold product by
the work it holds, which mass does not.
"""

from __future__ import annotations

import math
from functools import cache
from pathlib import Path

import yaml

#: Universal gas constant, kJ/(kmol K).
R = 8.314462618
DATA = Path(__file__).with_name("data") / "chemical-exergy.yaml"


@cache
def _table() -> dict:
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


def dead_state() -> tuple[float, float]:
    """(T0 in K, P0 in kPa(a)) of the tabulated chemical exergies."""
    state = _table()["dead_state"]
    return float(state["temperature"]), float(state["pressure"])


def source() -> str:
    return str(_table()["source"])


def standard(cas: str, phase: str = "gas") -> float | None:
    """The standard chemical exergy of *cas*, kJ/kmol (None when not tabulated)."""
    entry = _table()["substances"].get(cas)
    if entry is None:
        return None
    value = entry.get("liquid" if phase == "liquid" else "gas")
    return None if value is None else float(value) * 1000.0


def chemical(fractions: dict[str, float], phase: str = "gas") -> tuple[float | None, list[str]]:
    """The chemical exergy of a mixture of CAS numbers -> mole fractions, kJ/kmol, in the *phase*
    of its dead state (``gas`` or ``liquid``), and the CAS numbers that have no tabulated value
    for it (then None)."""
    t0, _ = dead_state()
    missing = [cas for cas, x in fractions.items() if x > 0 and standard(cas, phase) is None]
    if missing:
        return None, missing
    total = sum(x * standard(cas, phase) for cas, x in fractions.items() if x > 0)  # type: ignore[operator]
    mixing = R * t0 * sum(x * math.log(x) for x in fractions.values() if x > 0)
    return total + mixing, []


def physical(h: float, s: float, h0: float, s0: float) -> float:
    """``(h - h0) - T0 (s - s0)``, kJ/kmol, from molar enthalpies (kJ/kmol) and entropies
    (kJ/(kmol K))."""
    t0, _ = dead_state()
    return (h - h0) - t0 * (s - s0)


def stream_exergy(adapter, inputs, phase: str | None = None) -> tuple[float | None, list[str]]:
    """The molar exergy of a stream state, kJ/kmol, through the property method's public
    ``flash`` and ``entropy`` (:class:`chemeascode.domains.process.props.Adapter`), and the CAS
    numbers without a tabulated chemical exergy (then None). With *phase*, the state is that
    phase's root where the flash gives another (``Adapter.flash(inputs, phase)``). The dead
    state is the same composition at T0, P0 (the stable flash), which must itself be inside the
    method's claimed range; a state outside it raises the adapter's ``Unsupported``."""
    from chemeascode.domains.process.props import Inputs, Unsupported

    t0, p0 = dead_state()
    dead_inputs = Inputs(t0, p0, inputs.fractions)
    state, dead = adapter.flash(inputs, phase), adapter.flash(dead_inputs)
    if dead.phase == "two-phase":
        raise Unsupported("property-unsupported", "two-phase at the dead state")
    comps = adapter.process.components()
    by_cas = {comps[n].cas: x for n, x in inputs.fractions.items()}
    value, missing = chemical(by_cas, "gas" if dead.phase == "vapor" else "liquid")
    if value is None:
        return None, missing
    work = physical(
        state.enthalpy,
        adapter.entropy(inputs, phase),
        dead.enthalpy,
        adapter.entropy(dead_inputs),
    )
    return value + work, []
