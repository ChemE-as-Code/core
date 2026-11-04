"""The interface of an anolyte (electrolyte reservoir) model, and the registry of the models.

A dynamic electrolysis duty (:mod:`chemeascode.domains.process.electrolysis_duty`) integrates
the reservoir an electrochemical cell recirculates its anolyte through. What the reservoir
holds, how it is speciated and what its pH is are the business of an anolyte model; the duty
only hands it the ion fluxes from the cells, the dosing, make-up and bleed. A model implements
:class:`AnolyteModel`:

- ``id`` and ``version``: recorded with every result; a model's numbers do not change within a
  version;
- ``state``: the names and units of the state it carries (conserved quantities: moles of
  elements or ions that no reaction in the reservoir creates or destroys, and the volume),
  integrated by the caller;
- ``species``: the ions and molecules it accepts in the fluxes; any other is refused (the
  caller reports it, never drops it);
- ``initial(composition, volume_l)``: the state of a reservoir of *volume_l* litres of the
  composition (keys the model documents, in mol/L);
- ``rates(state, fluxes, t)``: d(state)/dt from the fluxes (mol/s of conserved quantities, L/s
  of volume), including what the model itself lets leave (``losses``);
- ``losses(state)``: mol/s leaving the reservoir by the model's own mechanisms (CO2 degassing),
  so the caller can account for them;
- ``speciate(state, volume_l)``: the pH and the concentration of every species
  (:class:`Speciation`), with the charge balance residual;
- ``validity``: the range (:class:`Validity`: ionic strength, pH, temperature) the model claims,
  and ``assumptions`` and ``limitations`` as text.

Models are found by id with :func:`anolyte_model`; an unknown id raises
:class:`UnknownAnolyteModel` (the caller reports it as a finding): there is no default model.
The first model is ``well-mixed-carbonate`` v1 (:mod:`chemeascode.domains.chemistry.carbonate`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Validity:
    """Where a model's speciation is claimed: ionic strength (mol/L), pH and temperature (K)
    ranges, each (min, max); None: not bounded by the model."""

    ionic_strength_mol_l: tuple[float, float] | None = None
    ph: tuple[float, float] | None = None
    temperature_k: tuple[float, float] | None = None
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ionic_strength_mol_l": list(self.ionic_strength_mol_l)
            if self.ionic_strength_mol_l
            else None,
            "ph": list(self.ph) if self.ph else None,
            "temperature_k": list(self.temperature_k) if self.temperature_k else None,
            "source": self.source,
        }


@dataclass(frozen=True)
class ReservoirFluxes:
    """What enters (positive) or leaves (negative) the reservoir, besides the model's own
    losses: ``ions`` from the cells (mol/s of each ion: OH- produced by the membrane and
    consumed at the anode, co-ions crossing the membrane), ``dosing`` (mol/s of each species
    added with a dosing solution, e.g. K+ and OH- of KOH), ``volume_in`` (L/s of solution or
    water added) and ``bleed`` (L/s of reservoir solution removed at its composition)."""

    ions: Mapping[str, float] = field(default_factory=dict)
    dosing: Mapping[str, float] = field(default_factory=dict)
    volume_in: float = 0.0
    bleed: float = 0.0


@dataclass(frozen=True)
class Speciation:
    """The state of a reservoir: pH (-log10 of the H+ concentration in mol/L, the model's
    basis), concentrations in mol/L by species, the ionic strength (mol/L), the charge balance
    residual (mol/L of charge) and the solver's iterations."""

    ph: float
    concentrations: Mapping[str, float]
    ionic_strength_mol_l: float
    charge_residual_mol_l: float
    iterations: int = 0

    def outside(self, validity: Validity, temperature_k: float | None = None) -> list[str]:
        """What of this state lies outside *validity* (empty: inside)."""
        out = []
        if validity.ph is not None and not validity.ph[0] <= self.ph <= validity.ph[1]:
            out.append(f"pH {self.ph:.4g} outside {validity.ph[0]:g}-{validity.ph[1]:g}")
        bound = validity.ionic_strength_mol_l
        if bound is not None and not bound[0] <= self.ionic_strength_mol_l <= bound[1]:
            out.append(
                f"ionic strength {self.ionic_strength_mol_l:.4g} mol/L outside "
                f"{bound[0]:g}-{bound[1]:g} mol/L"
            )
        span = validity.temperature_k
        if (
            temperature_k is not None
            and span is not None
            and not span[0] <= temperature_k <= span[1]
        ):
            out.append(f"temperature {temperature_k:.6g} K outside {span[0]:g}-{span[1]:g} K")
        return out


@runtime_checkable
class AnolyteModel(Protocol):
    """An anolyte (reservoir) model; see the module docstring."""

    id: str
    version: int
    #: (name, unit) of each state component, in the order of the state vector
    state: tuple[tuple[str, str], ...]
    #: the ions and molecules the fluxes may name
    species: tuple[str, ...]
    #: the composition keys :meth:`initial` takes (mol/L)
    composition_keys: tuple[str, ...]
    validity: Validity
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]

    def initial(self, composition: Mapping[str, float], volume_l: float) -> list[float]: ...

    def rates(self, state: Sequence[float], fluxes: ReservoirFluxes, t: float) -> list[float]: ...

    def losses(self, state: Sequence[float]) -> dict[str, float]: ...

    def speciate(self, state: Sequence[float], volume_l: float | None = None) -> Speciation: ...

    def describe(self) -> dict[str, Any]: ...


class UnknownAnolyteModel(LookupError):
    """No anolyte model of that id (``known`` lists those there are)."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.known = sorted(_REGISTRY)
        super().__init__(f"no anolyte model {model_id!r}; known: {', '.join(self.known)}")


#: id -> (module, class): the class takes the model's parameters as keyword arguments
_REGISTRY: dict[str, tuple[str, str]] = {
    "well-mixed-carbonate": ("chemeascode.domains.chemistry.carbonate", "WellMixedCarbonate"),
}


def anolyte_models() -> list[str]:
    """The ids of the registered anolyte models."""
    return sorted(_REGISTRY)


def anolyte_model(model_id: str, **parameters: Any) -> AnolyteModel:
    """The anolyte model *model_id* with its *parameters*; :class:`UnknownAnolyteModel` for an
    id that is not registered (never a default)."""
    if model_id not in _REGISTRY:
        raise UnknownAnolyteModel(model_id)
    module, name = _REGISTRY[model_id]
    return getattr(import_module(module), name)(**parameters)
