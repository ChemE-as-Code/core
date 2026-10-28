"""The solid/slurry material contract of the process model (pre-release issue 365).

A solid is a component of ``process/materials.yaml`` with ``phase: solid``: a crystal, or a
hydrate whose formula includes its water of crystallization (``MgSO4(H2O)7``). It is a separate
component from the same substance dissolved (``KNO3`` dissolved, ``KNO3_s`` the crystal), so that
stream compositions, mass balances and element balances need nothing new: a crystallizer turns
one component into another of the same elements, and is balanced on elements like a reactor.

Every material stream then divides into its **dry solid** (the sum of its solid components) and
its **liquid** (everything else: the mother liquor, or the moisture of a wet cake), each with its
own composition. :func:`slurry_basis` computes that division from a stream's flow and
composition; nothing in the flowsheet states it twice. There is no particle size, shape,
porosity or population balance: a solid is characterised by its mass and composition only, which
is what mass, element and energy balances, yields, recoveries and cake moisture need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def solid_components(process: Any) -> set[str]:
    """The ids of the components declared ``phase: solid``."""
    return {c.id for c in process.components().values() if getattr(c, "phase", None) == "solid"}


@dataclass
class SlurryBasis:
    """One stream in one case divided into dry solid and liquid (kg/h)."""

    stream: str
    total: float
    solid: float
    liquid: float
    #: Mass fractions of the dry solid and of the liquid, each summing to 1 (empty when zero).
    solid_composition: dict[str, float] = field(default_factory=dict)
    liquid_composition: dict[str, float] = field(default_factory=dict)

    @property
    def moisture(self) -> float | None:
        """Liquid over the total (wet) mass: a cake's moisture, a slurry's liquid fraction."""
        return self.liquid / self.total if self.total > 0 else None

    @property
    def liquid_per_solid(self) -> float | None:
        """kg of liquid per kg of dry solid (None without solid)."""
        return self.liquid / self.solid if self.solid > 0 else None

    def entry(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "total_kg_h": self.total,
            "dry_solid_kg_h": self.solid,
            "liquid_kg_h": self.liquid,
            "moisture_mass_fraction": self.moisture,
            "liquid_per_kg_solid": self.liquid_per_solid,
            "solid_composition": self.solid_composition,
            "liquid_composition": self.liquid_composition,
        }


def divide(stream: str, mass: dict[str, float], solids: set[str]) -> SlurryBasis:
    """*mass* (kg/h by component) divided into the components in *solids* and the rest."""
    solid = {n: v for n, v in mass.items() if n in solids and v}
    liquid = {n: v for n, v in mass.items() if n not in solids and v}
    s, w = sum(solid.values()), sum(liquid.values())
    return SlurryBasis(
        stream,
        s + w,
        s,
        w,
        {n: v / s for n, v in solid.items()} if s > 0 else {},
        {n: v / w for n, v in liquid.items()} if w > 0 else {},
    )


def slurry_basis(process: Any, stream: Any, case: str) -> SlurryBasis | None:
    """The dry solid and liquid of *stream* in *case*; None when its flow or composition (in
    kg/h per component) cannot be evaluated."""
    from chemeascode.domains.process.model import stream_flows

    flows = stream_flows(process, stream, case)
    if flows.components is None:
        return None
    return divide(stream.id, flows.components, solid_components(process))
