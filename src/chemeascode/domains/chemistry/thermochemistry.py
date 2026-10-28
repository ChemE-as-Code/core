"""Ideal-gas thermochemistry of components and reactions: enthalpy, entropy and Gibbs energy on
the elements basis, heats of reaction and equilibrium constants.

A component's ``ideal_gas`` data (in ``process/materials.yaml``) is its standard enthalpy of
formation and entropy at 298.15 K and 1 bar, and its ideal-gas heat capacity as a polynomial
``Cp/R = a0 + a1 T + a2 T^2 + a3 T^3 + a4 T^4`` (Poling, Prausnitz, O'Connell, *The Properties
of Gases and Liquids*, 5th ed., Appendix A, the form ``chemicals`` keeps), valid in
``temperature_range``. From it::

    h(T) = dHf_298 + R int_298.15^T Cp/R dT                        kJ/kmol
    s(T, P) = S_298 + R int_298.15^T Cp/R / T dT - R ln(P / 1 bar)  kJ/(kmol K)
    g(T) = h(T) - T s(T, 1 bar)

and for a reaction ``ln K(T) = -sum(nu_i g_i(T)) / (R T)`` on the standard state ideal gas at
1 bar: ``K = prod((y_i P / 1 bar)^nu_i)``. Pure Python; no optional dependency.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction

from pydantic import Field, field_validator

from chemeascode.domains.chemistry.reactions import parse_formula
from chemeascode.foundation.schema_base import Provenance, Strict

#: kJ/(kmol K)
R = 8.314462618
T_REF = 298.15
#: The standard pressure, kPa.
P_STANDARD = 100.0


class IdealGas(Strict):
    """Standard formation data and ideal-gas heat capacity of one component."""

    dHf_298: float = Field(description="kJ/kmol, ideal gas at 298.15 K and 1 bar")
    S_298: float = Field(description="kJ/(kmol K), ideal gas at 298.15 K and 1 bar")
    cp_R: list[float] = Field(
        min_length=1, max_length=5, description="Cp/R = a0 + a1 T + ... + a4 T^4 (T in K)"
    )
    temperature_range: tuple[float, float] | None = Field(
        default=None, description="K, where cp_R is valid (none: every temperature)"
    )
    provenance: Provenance = "given"
    source: str = ""

    @field_validator("temperature_range")
    @classmethod
    def _range(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and not 0 < value[0] < value[1]:
            raise ValueError("temperature_range is (min, max) in K, 0 < min < max")
        return value

    def covers(self, temperature: float) -> bool:
        return self.temperature_range is None or (
            self.temperature_range[0] <= temperature <= self.temperature_range[1]
        )

    def _cp_int(self, t: float) -> float:
        """int Cp/R dT from 0 (antiderivative)."""
        return sum(a * t ** (k + 1) / (k + 1) for k, a in enumerate(self.cp_R))

    def _cp_over_t_int(self, t: float) -> float:
        """int Cp/R / T dT (antiderivative)."""
        a = self.cp_R
        return a[0] * math.log(t) + sum(a[k] * t**k / k for k in range(1, len(a)))

    def cp(self, temperature: float) -> float:
        """kJ/(kmol K)."""
        return R * sum(a * temperature**k for k, a in enumerate(self.cp_R))

    def enthalpy(self, temperature: float) -> float:
        """kJ/kmol on the elements at 298.15 K."""
        return self.dHf_298 + R * (self._cp_int(temperature) - self._cp_int(T_REF))

    def entropy(self, temperature: float, pressure: float = P_STANDARD) -> float:
        """kJ/(kmol K) at *pressure* kPa."""
        return (
            self.S_298
            + R * (self._cp_over_t_int(temperature) - self._cp_over_t_int(T_REF))
            - R * math.log(pressure / P_STANDARD)
        )

    def gibbs(self, temperature: float) -> float:
        """kJ/kmol at 1 bar, on the elements basis of :meth:`enthalpy` and :meth:`entropy`.
        Note: an element's g is not 0 away from 298.15 K, but every reaction balances the
        elements, so their sum cancels in a reaction's Gibbs energy."""
        return self.enthalpy(temperature) - temperature * self.entropy(temperature)


def missing(names: Sequence[str], data: Mapping[str, IdealGas | None]) -> list[str]:
    """The names without ideal-gas data."""
    return [n for n in names if data.get(n) is None]


def outside(names: Sequence[str], data: Mapping[str, IdealGas | None], t: float) -> list[str]:
    """The names whose heat capacity is not valid at *t*."""
    return [n for n in names if (d := data.get(n)) is not None and not d.covers(t)]


def reaction_enthalpy(
    stoichiometry: Mapping[str, float], data: Mapping[str, IdealGas], temperature: float
) -> float:
    """kJ per kmol of extent at *temperature*."""
    return sum(nu * data[n].enthalpy(temperature) for n, nu in stoichiometry.items())


def reaction_gibbs(
    stoichiometry: Mapping[str, float], data: Mapping[str, IdealGas], temperature: float
) -> float:
    """kJ per kmol of extent at *temperature* and 1 bar."""
    return sum(nu * data[n].gibbs(temperature) for n, nu in stoichiometry.items())


def ln_k(
    stoichiometry: Mapping[str, float], data: Mapping[str, IdealGas], temperature: float
) -> float:
    """ln K on partial pressures in bar (ideal gas)."""
    return -reaction_gibbs(stoichiometry, data, temperature) / (R * temperature)


def mixture_enthalpy(moles: Mapping[str, float], data: Mapping[str, IdealGas], t: float) -> float:
    """kW (kJ/s) of a flow of *moles* (kmol/h) at *t*: ideal gas, elements basis."""
    return sum(n * data[name].enthalpy(t) for name, n in moles.items() if n) / 3600.0


def independent_reactions(
    species: Sequence[str], formulas: Mapping[str, str]
) -> list[dict[str, float]]:
    """A basis of the reactions among *species* that balance the elements (the null space of
    the element matrix), with integer coefficients: what a Gibbs reactor can do. Raises
    ValueError when a formula is missing or unreadable."""
    atoms = {}
    for name in species:
        found = parse_formula(formulas.get(name, ""))
        if found is None:
            raise ValueError(f"no readable formula for {name}")
        atoms[name] = found
    elements = sorted({e for a in atoms.values() for e in a})
    # rows: elements, columns: species; reduced row echelon form over the rationals
    rows = [[Fraction(atoms[s].get(e, 0)) for s in species] for e in elements]
    pivots: list[int] = []
    r = 0
    for c in range(len(species)):
        pivot = next((i for i in range(r, len(rows)) if rows[i][c] != 0), None)
        if pivot is None:
            continue
        rows[r], rows[pivot] = rows[pivot], rows[r]
        p = rows[r][c]
        rows[r] = [v / p for v in rows[r]]
        for i in range(len(rows)):
            if i != r and rows[i][c] != 0:
                f = rows[i][c]
                rows[i] = [v - f * w for v, w in zip(rows[i], rows[r], strict=True)]
        pivots.append(c)
        r += 1
    basis = []
    for free in (c for c in range(len(species)) if c not in pivots):
        vector = [Fraction(0)] * len(species)
        vector[free] = Fraction(1)
        for i, c in enumerate(pivots):
            vector[c] = -rows[i][free]
        scale = math.lcm(*(v.denominator for v in vector))
        ints = [int(v * scale) for v in vector]
        g = math.gcd(*ints) or 1
        basis.append({s: v // g for s, v in zip(species, ints, strict=True) if v})
    return basis


def inert_species(species: Sequence[str], formulas: Mapping[str, str]) -> list[str]:
    """The *species* that take part in no reaction a Gibbs reactor can do (none of
    :func:`independent_reactions`, whichever basis is taken: their coefficient is 0 in the
    whole null space), e.g. argon, or N2 among species without another nitrogen compound. They
    pass through: they need no formation data, only a heat capacity for the energy balance.
    Raises ValueError when a formula is missing or unreadable."""
    used = {n for r in independent_reactions(species, formulas) for n in r}
    return [n for n in species if n not in used]


def lookup_ideal_gas(
    identifier: str, fit: tuple[float, float] | None = None
) -> tuple[IdealGas, dict[str, object]]:
    """The ideal-gas data of *identifier* (name or CAS number) from ``chemicals`` (extra
    ``props``), with its source, and the identity (``cas``, ``name``, ``formula``,
    ``molar_mass``). With *fit* (K, min and max), the heat capacity is Poling's polynomial
    fitted to thermo's ideal-gas heat capacity over that range, instead of Poling's own
    coefficients (valid to 1000 K at most); without Poling's coefficients the fit runs from
    298.15 to 1000 K. Raises ValueError when a value is not known."""
    from chemeascode.integrations.thermo import fitted_cp_R, ideal_gas_formation

    found = ideal_gas_formation(identifier)
    sources = found["sources"]
    cp_R = found["cp_R"]
    window = found["temperature_range"]
    cp_source = f"cp_R {sources['cp_R']}"
    narrower = fit is None and cp_R is None
    if narrower:
        fit = (298.15, 1000.0)  # no Poling coefficients: fitted to thermo over Poling's range
    if fit is not None:
        fitted = fitted_cp_R(found["cas"], fit, narrower=narrower)
        fit = fitted["range"]
        top = fit[1]
        cp_R = list(fitted["cp_R"])
        while len(cp_R) > 1 and abs(cp_R[-1] * top ** (len(cp_R) - 1)) < 1e-9 * abs(cp_R[0]):
            cp_R.pop()
        window = fit
        cp_source = (
            f"cp_R fitted to thermo {fitted['method']} {fit[0]:g}-{fit[1]:g} K "
            f"(max deviation {fitted['max_deviation']:.2%})"
        )
    data = IdealGas(
        dHf_298=found["dHf_298"],
        S_298=found["S_298"],
        cp_R=cp_R,
        temperature_range=window,
        provenance="given",
        source=f"chemicals: dHf_298 {sources['dHf_298']}, S_298 {sources['S_298']}, {cp_source}",
    )
    identity = {k: found[k] for k in ("cas", "name", "formula", "molar_mass")}
    return data, identity
