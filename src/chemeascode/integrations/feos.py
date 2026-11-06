"""PC-SAFT through ``feos`` (extra ``saft``, pinned): the calculations the property adapter of a
PC-SAFT package needs (``domains/process/props_feos.py``), on the parameter files the caller
names. SI units throughout (K, Pa, mol/m3). feos and si_units are imported inside the functions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class FeosError(ValueError):
    """feos could not calculate the state (no convergence, unknown component)."""


def versions() -> dict[str, str]:
    from importlib.metadata import version

    return {name: version(name) for name in ("feos", "si-units")}


def installed() -> bool:
    try:
        import feos  # noqa: F401
    except ImportError:
        return False
    return True


class PcSaft:
    """PC-SAFT for the components *cas* (CAS numbers, in this order), with the pure-component
    records of *pure* and the binary records of *binary* (feos JSON, identified by CAS number)."""

    def __init__(self, cas: Sequence[str], pure: Path, binary: Path | None = None) -> None:
        import feos

        self.cas = tuple(cas)
        try:
            parameters = feos.Parameters.from_json(
                list(self.cas),
                str(pure),
                str(binary) if binary is not None and len(self.cas) > 1 else None,
                identifier_option=feos.IdentifierOption.Cas,
            )
            self._eos = feos.EquationOfState.pcsaft(parameters)
        except (RuntimeError, ValueError) as failure:
            raise FeosError(f"no PC-SAFT parameters for {', '.join(self.cas)}: {failure}") from None

    def _state(self, temperature: float, pressure: float, x: Sequence[float], root: str) -> Any:
        import feos
        import numpy as np
        import si_units as si

        try:
            return feos.State(
                self._eos,
                temperature=temperature * si.KELVIN,
                pressure=pressure * si.PASCAL,
                composition=np.asarray(x, dtype=float),
                density_initialization=root,
            )
        except RuntimeError as failure:
            raise FeosError(
                f"no {root} state at {temperature:g} K, {pressure:g} Pa: {failure}"
            ) from None

    def liquid_density(self, temperature: float, pressure: float, x: Sequence[float]) -> float:
        """Molar density of the liquid root at *temperature*, *pressure* and mole fractions *x*,
        mol/m3. feos finds a dense root also where the liquid is not stable: the caller decides
        the phase (:meth:`bubble_pressure`)."""
        import si_units as si

        state = self._state(temperature, pressure, x, "liquid")
        return float(state.density / (si.MOL / si.METER**3))

    def bubble_pressure(self, temperature: float, x: Sequence[float]) -> float:
        """Bubble-point pressure of the liquid *x* at *temperature*, Pa (the vapour pressure for
        one component)."""
        import feos
        import si_units as si

        try:
            if len(self.cas) == 1:
                vle = feos.PhaseEquilibrium.pure(self._eos, temperature * si.KELVIN)
            else:
                vle = feos.PhaseEquilibrium.bubble_point(
                    self._eos, temperature * si.KELVIN, list(x)
                )
        except RuntimeError as failure:
            raise FeosError(f"no bubble point at {temperature:g} K: {failure}") from None
        return float(vle.liquid.pressure() / si.PASCAL)

    def metastability(self, temperature: float, pressure: float, x: Sequence[float]) -> float:
        """``(G_liquid - G_stable) / RT`` of the liquid root at *temperature*, *pressure*, *x*
        (0 when the liquid is the stable state): the stable state is the vapour-liquid split of a
        tp flash, else the lower of the liquid and vapour roots. The molar Gibbs energy is taken
        as ``RT sum x_i ln(x_i phi_i)``: the pure components' ideal-gas terms and ``ln p`` are
        the same for every state at this temperature, pressure and overall composition."""
        import feos
        import numpy as np
        import si_units as si

        def g(state: Any) -> float:
            xs = np.asarray(state.molefracs, dtype=float)
            lnphi = np.asarray(state.ln_phi(), dtype=float)
            present = xs > 0
            return float(np.sum(xs[present] * (np.log(xs[present]) + lnphi[present])))

        liquid = self._state(temperature, pressure, x, "liquid")
        stable = min(g(liquid), g(self._state(temperature, pressure, x, "vapor")))
        if len(self.cas) > 1:
            try:
                split = feos.PhaseEquilibrium.tp_flash(
                    self._eos, temperature * si.KELVIN, pressure * si.PASCAL, np.asarray(x)
                )
            except RuntimeError:
                split = None  # no split: one of the roots is the stable state
            if split is not None:
                beta = float(split.vapor_phase_fraction)
                if 0.0 < beta < 1.0:
                    stable = min(stable, (1 - beta) * g(split.liquid) + beta * g(split.vapor))
        excess = g(liquid) - stable
        return 0.0 if not math.isfinite(excess) or excess < 0 else excess
