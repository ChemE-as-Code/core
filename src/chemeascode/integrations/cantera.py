"""Cantera (optional extra ``cantera``): the steady state of a surface mechanism given as a
Cantera YAML input (:func:`chemeascode.domains.chemistry.microkinetics.cantera_yaml` writes
one), the NASA thermochemical data of gas and condensed species that Cantera ships
(:func:`nasa_species`, :func:`nasa_properties`; the furnace energy basis of
:mod:`chemeascode.domains.process.furnace` uses them), and the state of an aqueous electrolyte
solution of Cantera's ``HMW-electrolyte`` phase (Pitzer's equations, :func:`hmw_state`;
:func:`chemeascode.domains.process.thermodynamics.electrolytes.cantera_input` writes one).
cantera is imported inside the functions only."""

from __future__ import annotations

import functools
from collections.abc import Iterable, Mapping
from typing import Any

SITE = "*"
#: The free site's name in the exported input.
FREE = "free(s)"
#: Cantera's data files of the NASA Glenn coefficients (McBride, Gordon and Reno, NASA
#: TM-4513, 1993), searched in this order for a species name.
NASA_FILES = ("nasa_gas.yaml", "nasa_condensed.yaml")


@functools.cache
def _nasa() -> dict[str, tuple[str, Any]]:
    import cantera as ct

    species: dict[str, tuple[str, Any]] = {}
    for file in NASA_FILES:
        for one in ct.Species.list_from_file(file):
            species.setdefault(one.name, (file, one))
    return species


def version() -> str:
    import cantera as ct

    return ct.__version__


def nasa_species(names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Per NASA species name: its ``file``, elemental ``composition``, ``temperature_ranges``
    (K, the polynomial breakpoints: data are valid from the first to the last),
    ``reference_pressure`` (kPa, as Cantera declares it: 1 atm for these files converted from
    Chemkin format, although TM-4513's data are on 1 bar) and the data ``note`` (source and
    date code of McBride et al.).
    Raises KeyError naming a species neither file holds."""
    table = _nasa()
    out = {}
    for name in names:
        if name not in table:
            raise KeyError(f"{name!r} is not in Cantera's {' or '.join(NASA_FILES)}")
        file, species = table[name]
        thermo = species.input_data["thermo"]
        out[name] = {
            "file": file,
            "composition": {e: float(n) for e, n in species.composition.items()},
            "temperature_ranges": [float(t) for t in thermo["temperature-ranges"]],
            "reference_pressure": species.thermo.reference_pressure / 1000.0,
            "note": str(thermo.get("note", "")),
        }
    return out


def nasa_properties(name: str, temperature: float) -> tuple[float, float, float]:
    """Enthalpy (kJ/kmol, on the elements in their reference states at 298.15 K), entropy and
    heat capacity (kJ/(kmol K)) of the NASA species *name* at *temperature* K and its reference
    pressure. Cantera extrapolates outside the species' range without a warning: the caller
    checks the range (:func:`nasa_species`)."""
    thermo = _nasa()[name][1].thermo
    return (
        thermo.h(temperature) / 1000.0,
        thermo.s(temperature) / 1000.0,
        thermo.cp(temperature) / 1000.0,
    )


def run(text: str, temperature: float, pressures: Mapping[str, float]) -> dict[str, Any]:
    """The steady coverages and the net production per site (1/s) of the gas components of
    the exported mechanism *text* at *temperature* K and partial *pressures* (bar)."""
    import cantera as ct

    try:
        gas = ct.Solution(yaml=text, name="gas")
        surface = ct.Interface(yaml=text, name="surface", adjacent=[gas])
        # the mechanism's gas only: a diluent changes no partial pressure the steps see
        mine = {k: v for k, v in pressures.items() if k in gas.species_names and v > 0}
        total = sum(mine.values())
        if total <= 0:
            raise ValueError("no partial pressure of a component of the mechanism")
        gas.TPX = temperature, total * 1e5, {k: v / total for k, v in mine.items()}
        surface.TP = temperature, total * 1e5
        surface.advance_coverages_to_steady_state()
    except ct.CanteraError as failure:
        raise ValueError(f"Cantera: {str(failure).strip().splitlines()[-1]}") from failure
    gamma = surface.site_density
    production = dict(
        zip(gas.species_names, surface.get_net_production_rates(gas) / gamma, strict=True)
    )
    coverages = dict(zip(surface.species_names, surface.coverages, strict=True))
    return {
        "coverages": {
            (SITE if k == FREE else k[:-3] + SITE): float(v) for k, v in coverages.items()
        },
        "production": {k: float(v) for k, v in production.items()},
        "version": ct.__version__,
    }


def hmw_state(
    text: str, temperature: float, pressure: float, molalities: Mapping[str, float]
) -> dict[str, Any]:
    """The state of the ``HMW-electrolyte`` phase of *text* at *temperature* K, *pressure* Pa
    and solute *molalities* (mol per kg of the solvent, the phase's first species), per kg of
    solvent:

    - ``amounts``: mol of each species; ``charges``; ``elements``: mol of each element;
    - ``activities``: the solvent's on the mole-fraction scale (pure solvent), the solutes' on
      the molality scale (1 mol/kg);
    - ``relative_enthalpies``: each species' partial molar enthalpy minus its standard-state
      enthalpy at T and P, J/mol (so independent of the standard-state data).
    """
    import cantera as ct

    try:
        phase = ct.Solution(yaml=text)
        solvent = phase.species_names[0]
        solvent_molar_mass = phase.molecular_weights[0] / 1000.0  # kg/mol
        unknown = sorted(set(molalities) - set(phase.species_names[1:]))
        if unknown:
            raise ValueError(f"no solute {', '.join(unknown)} in the phase")
        per_kg = {solvent: 1.0 / solvent_molar_mass}
        per_kg.update({s: float(molalities.get(s, 0.0)) for s in phase.species_names[1:]})
        total = sum(per_kg.values())
        phase.TPX = temperature, pressure, {s: n / total for s, n in per_kg.items()}
        rt = ct.gas_constant * temperature  # J/kmol
        relative = (
            phase.partial_molar_enthalpies - phase.standard_enthalpies_RT * rt
        ) / 1000.0  # J/mol
        activities = phase.activities
    except ct.CanteraError as failure:
        raise ValueError(f"Cantera: {str(failure).strip().splitlines()[-1]}") from failure
    x_solvent = phase.X[0]
    amounts = {
        s: float(x / x_solvent / solvent_molar_mass)
        for s, x in zip(phase.species_names, phase.X, strict=True)
    }
    elements = {
        e: sum(phase.n_atoms(s, e) * n for s, n in amounts.items()) for e in phase.element_names
    }
    return {
        "solvent": solvent,
        "solvent_molar_mass": solvent_molar_mass,
        "amounts": amounts,
        "charges": dict(zip(phase.species_names, map(float, phase.charges), strict=True)),
        "elements": {e: float(n) for e, n in elements.items()},
        "activities": dict(zip(phase.species_names, map(float, activities), strict=True)),
        "relative_enthalpies": dict(zip(phase.species_names, map(float, relative), strict=True)),
        "version": ct.__version__,
    }
