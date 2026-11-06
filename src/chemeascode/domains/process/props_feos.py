"""Stream properties on PC-SAFT through feos (:mod:`chemeascode.integrations.feos`, extra
``saft``): the adapter of a property package with ``adapter="feos"`` (``props.adapter_for``
picks it). The one such package, ``water-methanol-pcsaft-liquid``, claims liquid density only
(ADR 0046):

- **phase**: PC-SAFT's bubble pressures miss the measured ones by up to the benchmark's
  ``bubble_pressure_rel`` (*m*), so a state is liquid when its pressure is at least ``(1 + m)``
  times PC-SAFT's bubble pressure. Closer to it, or below it, the phase is not established and the
  state is refused, unless the stream's phase is given or assumed ``liquid``: then down to the
  bubble pressure divided by ``(1 + m)`` its liquid root is used, phase-constrained when below the
  bubble pressure itself (the result names the metastability, ``(G_liquid - G_stable) / RT``).
  A liquid given further below is refused (``property-phase``); vapour and two-phase states are
  never claimed;
- **density**: the liquid root's molar density times the package's molar masses;
- **enthalpy**: not claimed (``Result.enthalpy`` is None), nor entropy, Cp/Cv, bubble and dew
  points, K values or viscosity: each refuses with ``property-unsupported``.

The parameters are the records in ``thermodynamics/data/feos/`` (SOURCE.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chemeascode.domains.process.model import Process
from chemeascode.domains.process.props import (
    Inputs,
    Result,
    Unsupported,
    package_of,
    range_problems,
)

DATA = Path(__file__).parent / "thermodynamics" / "data" / "feos"
#: The pure-component records (Esper et al. 2023) and the binary ones (Rehner et al. 2023).
PURE = DATA / "pcsaft-esper2023.json"
BINARY = DATA / "pcsaft-rehner2023-binary.json"


class FeosAdapter:
    """PC-SAFT for the process's package, one model per set of components present."""

    def __init__(self, process: Process) -> None:
        from chemeascode.integrations import feos

        if not feos.installed():
            raise Unsupported(
                "property-unsupported",
                "feos is not installed: install cheme-as-code with the saft extra "
                "(uv tool install 'cheme-as-code[saft]')",
            )
        self.process = process
        self.package = package_of(process)
        self._models: dict[tuple[str, ...], Any] = {}

    @property
    def margin(self) -> float:
        """The benchmarked bubble-pressure deviation, as a fraction."""
        return self.package.benchmark.tolerances["bubble_pressure_rel"]

    def _model(self, cas: tuple[str, ...]) -> Any:
        from chemeascode.integrations.feos import FeosError, PcSaft

        if cas not in self._models:
            try:
                self._models[cas] = PcSaft(cas, PURE, BINARY)
            except FeosError as failure:
                raise Unsupported("property-unsupported", str(failure)) from failure
        return self._models[cas]

    def _composition(self, fractions: dict[str, float]) -> tuple[tuple[str, ...], list[float]]:
        """The CAS numbers present (sorted) and their mole fractions."""
        comps = self.process.components()
        by_cas: dict[str, float] = {}
        for name, x in fractions.items():
            by_cas[comps[name].cas] = by_cas.get(comps[name].cas, 0.0) + x
        cas = tuple(sorted(by_cas))
        return cas, [by_cas[c] for c in cas]

    def flash(self, inputs: Inputs, phase: str | None = None) -> Result:
        """The liquid density at *inputs*; :class:`Unsupported` when the package does not claim
        the state. With *phase* ``liquid`` (given or assumed), a state the bubble-pressure margin
        leaves undecided is calculated on the liquid root."""
        from chemeascode.integrations.feos import FeosError

        problems = range_problems(self.process, inputs)
        if problems:
            raise Unsupported(*problems[0])
        if phase == "vapor":
            raise Unsupported(
                "property-unsupported",
                f"phase vapor is not claimed (package {self.package.id} claims liquid only)",
            )
        cas, x = self._composition(inputs.fractions)
        model = self._model(cas)
        pressure = inputs.pressure * 1000.0
        where = f"{inputs.temperature:.3f} K, {inputs.pressure:g} kPa(a)"
        try:
            bubble = model.bubble_pressure(inputs.temperature, x)
        except FeosError as failure:
            raise Unsupported("property-unsupported", f"bubble point failed: {failure}") from None
        factor = 1.0 + self.margin
        stable_phase = metastability = None
        if phase != "liquid" and pressure < factor * bubble:
            if pressure < bubble:
                raise Unsupported(
                    "property-unsupported",
                    f"below PC-SAFT's bubble pressure {bubble / 1000:.4g} kPa(a) at {where}: "
                    f"vapour or two-phase, which package {self.package.id} does not claim "
                    "(liquid only)",
                )
            raise Unsupported(
                "property-unsupported",
                f"{where} is within {self.margin:.0%} of PC-SAFT's bubble pressure "
                f"{bubble / 1000:.4g} kPa(a), the deviation its bubble pressures have from "
                "measured ones: liquid is not established; give the stream's phase as liquid "
                "(given or assumed) if it is",
            )
        if phase == "liquid" and pressure < bubble:
            if pressure < bubble / factor:
                raise Unsupported(
                    "property-phase",
                    f"liquid at {where}, but PC-SAFT's bubble pressure is {bubble / 1000:.4g} "
                    f"kPa(a), more than the benchmarked {self.margin:.0%} above it: the state is "
                    "vapour or two-phase",
                )
            try:
                metastability = model.metastability(inputs.temperature, pressure, x)
            except FeosError as failure:
                raise Unsupported("property-phase", str(failure)) from None
            if metastability > 0.0:
                stable_phase = "two-phase"
        molar_mass = sum(xi * self.package.molar_masses[c] for c, xi in zip(cas, x, strict=True))
        try:
            density = model.liquid_density(inputs.temperature, pressure, x) * molar_mass / 1000.0
        except FeosError as failure:
            raise Unsupported("property-unsupported", str(failure)) from None
        return Result(
            molar_mass=molar_mass,
            phase="liquid",
            vapor_fraction=0.0,
            density=density,
            enthalpy=None,
            stable_phase=stable_phase,
            metastability=metastability if stable_phase else None,
        )

    def _not_claimed(self, what: str) -> Unsupported:
        return Unsupported(
            "property-unsupported",
            f"{what}: package {self.package.id} claims liquid density only",
        )

    def entropy(self, inputs: Inputs, phase: str | None = None) -> float:
        raise self._not_claimed("entropy")

    def heat_capacity_ratio(self, inputs: Inputs) -> float:
        raise self._not_claimed("Cp/Cv")

    def flash_ps(self, pressure: float, entropy: float, fractions: dict[str, float]) -> Result:
        raise self._not_claimed("a pressure-entropy flash")

    def flash_ph(self, pressure: float, enthalpy: float, fractions: dict[str, float]) -> Result:
        raise self._not_claimed("a pressure-enthalpy flash")

    def saturation_temperature(
        self, pressure: float, fractions: dict[str, float], vapor_fraction: float = 0.0
    ) -> float:
        raise self._not_claimed("saturation temperature")

    def bubble_pressure(self, temperature: float, fractions: dict[str, float]) -> float:
        raise self._not_claimed("bubble pressure")

    def k_values(
        self, pressure: float, fractions: dict[str, float], vapor_fraction: float = 0.0
    ) -> tuple[float, dict[str, float]]:
        raise self._not_claimed("equilibrium ratios")

    def liquid_viscosity(
        self, temperature: float, fractions: dict[str, float]
    ) -> tuple[float, str]:
        raise self._not_claimed("liquid viscosity")

    def _raw(self, fractions: dict[str, float], **spec: float) -> Any:
        raise self._not_claimed("a flash at " + ", ".join(sorted(spec)))

    def _checked(self, temperature: float, pressure: float, fractions: dict[str, float]) -> None:
        problems = range_problems(self.process, Inputs(temperature, pressure, fractions))
        if problems:
            raise Unsupported(*problems[0])
