"""Mean-field microkinetic models: the elementary surface steps of a catalytic reaction, their
steady state, and what controls its rate.

A reaction's ``mechanism`` (in ``process/reactions.yaml``) lists its adsorbates (ids ending in
``*``, e.g. ``CO*``; the formula is the id without the ``*``), the free site ``*``, and its
elementary steps, each with stoichiometry over gas components, adsorbates and ``*``::

    rate of a step per site (1/s)  r = k_f prod(theta^nu) prod(p^nu) - k_r prod(theta^nu) prod(p^nu)

with coverages theta (the free sites ``*`` included, summing to 1), partial pressures p in bar,
``k = A (T / T_ref)^n exp(-Ea / (R T))`` in 1/s per site, and for an adsorption step (one gas
molecule on free sites) a sticking coefficient instead of A:
``k_f = s exp(-Ea / (R T)) * 1e5 / (sqrt(2 pi m k_B T) Gamma N_A)`` per bar (the Hertz-Knudsen
flux per site, Gamma the site density in mol/m2). The steady state solves d theta / dt = 0 by
pseudo-transient continuation (implicit Euler steps of growing size, Newton with a
finite-difference Jacobian). From it come the turnover frequency (TOF: net production of a gas
component per site and second), the degree of rate control of each step (Campbell, J. Catal.
204 (2001) 520: X_i = d ln r / d ln k_i at constant equilibrium constant), the apparent
activation energy (R T^2 d ln r / dT) and the reaction orders (d ln r / d ln p). Pure Python.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field, model_validator

from chemeascode.domains.chemistry.formulas import parse_formula
from chemeascode.foundation.schema_base import Provenance, Strict

#: J/(mol K), 1/mol, J/K
R_J = 8.314462618
N_A = 6.02214076e23
K_B = 1.380649e-23
SITE = "*"


class StepRate(Strict):
    """``k = A (T/T_ref)^n exp(-Ea / (R T))`` per site and second (pressures in bar)."""

    A: float = Field(gt=0)
    Ea: float = Field(default=0.0, description="kJ/kmol (numerically J/mol)")
    n: float = 0.0
    T_ref: float = Field(default=1.0, gt=0, description="K")

    def k(self, temperature: float) -> float:
        return (
            self.A * (temperature / self.T_ref) ** self.n * math.exp(-self.Ea / (R_J * temperature))
        )


class Sticking(Strict):
    """An adsorption's sticking coefficient ``s = s0 exp(-Ea / (R T))``."""

    s0: float = Field(gt=0, le=1)
    Ea: float = Field(default=0.0, description="kJ/kmol (numerically J/mol)")


#: J/mol per eV, Planck's constant (J s)
EV = 96485.33212
H_PLANCK = 6.62607015e-34


class StepEnergies(Strict):
    """A step from electronic energies (DFT, e.g. from Catalysis-Hub or a paper): transition
    state theory, ``k = (k_B T / h) exp(-Ea / (R T))`` both ways, the forward barrier as given
    and the reverse ``barrier - reaction_energy``. An adsorption keeps its sticking coefficient
    and takes its desorption from these energies."""

    reaction_energy: float = Field(description="eV, products minus reactants")
    barrier: float = Field(ge=0, description="eV, forward (0: none)")
    provenance: Provenance
    source: str = Field(default="", description="The DOI or database entry.")

    @model_validator(mode="after")
    def _barrier(self) -> StepEnergies:
        if self.barrier < self.reaction_energy:
            raise ValueError(
                f"barrier {self.barrier:g} eV below the reaction energy {self.reaction_energy:g} "
                "eV: the reverse barrier would be negative"
            )
        return self

    def rates(self) -> tuple[StepRate, StepRate]:
        """(forward, reverse) as Arrhenius constants: A = k_B / h with n = 1."""
        prefactor = K_B / H_PLANCK
        return (
            StepRate(A=prefactor, Ea=self.barrier * EV, n=1.0),
            StepRate(A=prefactor, Ea=(self.barrier - self.reaction_energy) * EV, n=1.0),
        )


class Step(Strict):
    id: str
    equation: str = Field(default="", description="As text, for readers.")
    stoichiometry: dict[str, float] = Field(
        min_length=2,
        description="Gas component ids, adsorbates (X*) and the free site (*): negative "
        "consumed, positive formed.",
    )
    forward: StepRate | None = None
    sticking: Sticking | None = Field(
        default=None, description="Adsorption steps: instead of forward."
    )
    reverse: StepRate | None = Field(default=None, description="None: the step is irreversible.")
    energies: StepEnergies | None = Field(
        default=None,
        description="Instead of forward and reverse: electronic energies (transition state "
        "theory); with sticking, they give the desorption.",
    )

    @model_validator(mode="after")
    def _rate(self) -> Step:
        if self.energies is not None:
            if self.forward is not None or self.reverse is not None:
                raise ValueError(f"step {self.id}: energies replace forward and reverse")
            return self
        if (self.forward is None) == (self.sticking is None):
            raise ValueError(f"step {self.id}: give forward or sticking (one of them)")
        return self

    def constants(self) -> tuple[StepRate | None, StepRate | None]:
        """The step's (forward, reverse) Arrhenius constants (forward None: sticking)."""
        if self.energies is None:
            return self.forward, self.reverse
        forward, reverse = self.energies.rates()
        return (None if self.sticking is not None else forward), reverse

    def gas(self) -> list[str]:
        return [n for n in self.stoichiometry if not n.endswith(SITE)]


class Mechanism(Strict):
    """The elementary steps of one overall reaction on one kind of site."""

    site_density: float = Field(gt=0, description="mol/m2 of surface sites (Gamma)")
    adsorbates: list[str] = Field(min_length=1, description="Ids ending in *, e.g. CO*.")
    steps: list[Step] = Field(min_length=1)
    catalyst: str = Field(
        default="", description="The catalyst it describes (an id of process/catalysts.yaml)."
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _species(self) -> Mechanism:
        bad = [a for a in self.adsorbates if not a.endswith(SITE) or a == SITE]
        if bad:
            raise ValueError(f"adsorbates end in * and are not the free site: {', '.join(bad)}")
        ids = [step.id for step in self.steps]
        if twice := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"step ids are not unique: {', '.join(twice)}")
        surface = {*self.adsorbates, SITE}
        for step in self.steps:
            unknown = [n for n in step.stoichiometry if n.endswith(SITE) and n not in surface]
            if unknown:
                raise ValueError(f"step {step.id}: {', '.join(unknown)} is no adsorbate")
            consumed = [n for n in step.gas() if step.stoichiometry[n] < 0]
            if step.sticking is not None and (
                len(consumed) != 1 or step.stoichiometry[consumed[0]] != -1
            ):
                raise ValueError(f"step {step.id}: a sticking step adsorbs one gas molecule")
        return self


def step_atoms(step: Step, formulas: Mapping[str, str]) -> dict[str, float] | None:
    """Atoms the step creates by element (empty: balanced); None when a formula is unknown.
    An adsorbate's formula is its id without the trailing ``*``."""
    change: dict[str, float] = {}
    for name, nu in step.stoichiometry.items():
        if name == SITE:
            continue
        formula = name[:-1] if name.endswith(SITE) else formulas.get(name, "")
        atoms = parse_formula(formula)
        if atoms is None:
            return None
        for element, count in atoms.items():
            change[element] = change.get(element, 0.0) + nu * count
    return {e: v for e, v in change.items() if abs(v) > 1e-9}


def site_change(step: Step) -> float:
    """Sites the step creates (non-zero: it does not conserve sites)."""
    return sum(v for n, v in step.stoichiometry.items() if n.endswith(SITE))


@dataclass
class SteadyState:
    """The steady state of a mechanism at one temperature, pressure and gas composition."""

    temperature: float  # K
    pressures: dict[str, float]  # bar
    coverages: dict[str, float]  # the free site * included
    rates: dict[str, float]  # net rate of each step, 1/s per site
    production: dict[str, float]  # net production of each gas component, 1/s per site
    #: filled by :func:`analyse`
    rate_control: dict[str, float] = field(default_factory=dict)
    apparent_activation: float | None = None  # kJ/kmol
    orders: dict[str, float] = field(default_factory=dict)

    def tof(self, component: str) -> float:
        return self.production.get(component, 0.0)


class NoSteadyState(ValueError):
    """The coverages did not converge."""


def _constants(mech: Mechanism, temperature: float, masses: Mapping[str, float], scale=None):
    """(k_f, k_r) of every step at *temperature*; *scale*: step id -> factor on both (the
    degree of rate control)."""
    out = []
    for step in mech.steps:
        if step.sticking is not None:
            gas = next(n for n in step.gas() if step.stoichiometry[n] < 0)
            mass = masses[gas] / 1000.0 / N_A  # kg per molecule
            flux = 1e5 / math.sqrt(2 * math.pi * mass * K_B * temperature)  # per m2 s bar
            s = step.sticking.s0 * math.exp(-step.sticking.Ea / (R_J * temperature))
            kf = s * flux / (mech.site_density * N_A)
        else:
            kf = step.constants()[0].k(temperature)  # type: ignore[union-attr]
        reverse = step.constants()[1]
        kr = reverse.k(temperature) if reverse is not None else 0.0
        factor = (scale or {}).get(step.id, 1.0)
        out.append((kf * factor, kr * factor))
    return out


def _directions(
    mech, constants, theta: Mapping[str, float], p: Mapping[str, float]
) -> list[tuple[float, float]]:
    """(forward, backward) rate of every step, 1/s per site."""
    out = []
    for step, (kf, kr) in zip(mech.steps, constants, strict=True):
        forward, backward = kf, kr
        for name, nu in step.stoichiometry.items():
            value = theta.get(name, 0.0) if name.endswith(SITE) else p.get(name, 0.0)
            if nu < 0:
                forward *= value ** (-nu)
            else:
                backward *= value**nu
        out.append((forward, backward))
    return out


def _rates(mech, constants, theta: Mapping[str, float], p: Mapping[str, float]) -> list[float]:
    return [f - b for f, b in _directions(mech, constants, theta, p)]


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    m = len(b)
    rows = [[*a[i], b[i]] for i in range(m)]
    for col in range(m):
        best = max(range(col, m), key=lambda r: abs(rows[r][col]))
        if abs(rows[best][col]) < 1e-300:
            raise NoSteadyState("singular Jacobian")
        rows[col], rows[best] = rows[best], rows[col]
        for r in range(m):
            if r != col and rows[r][col]:
                f = rows[r][col] / rows[col][col]
                rows[r] = [v - f * w for v, w in zip(rows[r], rows[col], strict=True)]
    return [rows[i][m] / rows[i][i] for i in range(m)]


def steady_state(
    mech: Mechanism,
    temperature: float,
    pressures: Mapping[str, float],
    masses: Mapping[str, float],
    scale: Mapping[str, float] | None = None,
    start: Mapping[str, float] | None = None,
) -> SteadyState:
    """The steady coverages of *mech* at *temperature* K and gas partial *pressures* (bar);
    *masses*: molar masses (kg/kmol) of the adsorbing gas components."""
    constants = _constants(mech, temperature, masses, scale)
    # the unknowns: every adsorbate and the free site; the equations: d theta/dt of the
    # adsorbates and the site balance (so a nearly empty or nearly full surface keeps its digits)
    names = [*mech.adsorbates, SITE]
    known = start or {}
    x = [known.get(n, 0.0) for n in mech.adsorbates]
    x.append(max(1.0 - sum(x), 0.0) if start else 1.0)
    n_ads = len(mech.adsorbates)

    def change(values: list[float]) -> list[float]:
        cover = dict(zip(names, values, strict=True))
        rates = _rates(mech, constants, cover, pressures)
        return [
            sum(
                step.stoichiometry.get(n, 0.0) * r
                for step, r in zip(mech.steps, rates, strict=True)
            )
            for n in mech.adsorbates
        ]

    def system(values: list[float], previous: list[float], dt: float) -> list[float]:
        d = change(values)
        rows = [values[i] - previous[i] - dt * d[i] for i in range(n_ads)]
        rows.append(sum(values) - 1.0)
        return rows

    dt = 1e-12
    for _ in range(4000):
        cover = dict(zip(names, x, strict=True))
        both = _directions(mech, constants, cover, pressures)
        d = change(x)
        net = max((abs(f - b) for f, b in both), default=0.0)
        scale_gross = max((max(abs(f), abs(b)) for f, b in both), default=0.0)
        # converged when the coverages change far slower than the slowest net step runs (or,
        # at equilibrium, than the rounding of the gross rates)
        if dt > 1e8 and max((abs(v) for v in d), default=0.0) <= max(
            1e-9 * net, 1e-15 * scale_gross
        ):
            break
        y = list(x)
        for _ in range(40):
            g = system(y, x, dt)
            jac = [[0.0] * len(y) for _ in y]
            dy = change(y)
            for j in range(len(y)):
                # relative to the coverage itself, so a coverage of 1e-10 is resolved too
                h = 1.5e-8 * max(abs(y[j]), 1e-300)
                z = list(y)
                z[j] += h
                dz = change(z)
                for r in range(n_ads):
                    jac[r][j] = (1.0 if r == j else 0.0) - dt * (dz[r] - dy[r]) / h
                jac[n_ads][j] = 1.0  # the site balance, exactly
            delta = _solve_linear(jac, [-v for v in g])
            # damped: no coverage below a tenth of its value
            limit = 1.0
            for v, dv in zip(y, delta, strict=True):
                if dv < 0 and v > 0:
                    limit = min(limit, 0.9 * v / -dv)
            y = [max(v + limit * dv, 0.0) for v, dv in zip(y, delta, strict=True)]
            if (
                max(abs(limit * dv) / max(abs(v), 1e-300) for v, dv in zip(y, delta, strict=True))
                < 1e-13
            ):
                break
        x = y
        dt *= 3.0
    else:
        raise NoSteadyState("the coverages did not reach a steady state")
    cover = dict(zip(names, x, strict=True))
    rates = _rates(mech, constants, cover, pressures)
    production: dict[str, float] = {}
    for step, r in zip(mech.steps, rates, strict=True):
        for n in step.gas():
            production[n] = production.get(n, 0.0) + step.stoichiometry[n] * r
    return SteadyState(
        temperature,
        dict(pressures),
        cover,
        {s.id: r for s, r in zip(mech.steps, rates, strict=True)},
        production,
    )


def analyse(
    mech: Mechanism,
    temperature: float,
    pressures: Mapping[str, float],
    masses: Mapping[str, float],
    product: str,
    orders_of: Sequence[str] = (),
) -> SteadyState:
    """:func:`steady_state` with the degree of rate control of every step, the apparent
    activation energy and the reaction orders in *orders_of*, all for the TOF of *product*
    (central differences of 1 %)."""
    base = steady_state(mech, temperature, pressures, masses)
    r0 = base.tof(product)
    if r0 == 0:
        raise NoSteadyState(f"no net production of {product}")
    h = 0.01

    def ln_tof(**changes) -> float:
        state = steady_state(
            mech,
            changes.get("T", temperature),
            changes.get("p", pressures),
            masses,
            changes.get("scale"),
            start=base.coverages,
        )
        return math.log(abs(state.tof(product)))

    for step in mech.steps:
        up = ln_tof(scale={step.id: 1 + h})
        down = ln_tof(scale={step.id: 1 - h})
        base.rate_control[step.id] = (up - down) / (math.log(1 + h) - math.log(1 - h))
    t_up, t_down = temperature * (1 + h), temperature * (1 - h)
    slope = (ln_tof(T=t_up) - ln_tof(T=t_down)) / (1 / t_down - 1 / t_up)
    base.apparent_activation = slope * R_J  # J/mol = kJ/kmol
    for name in orders_of:
        up = ln_tof(p={**pressures, name: pressures[name] * (1 + h)})
        down = ln_tof(p={**pressures, name: pressures[name] * (1 - h)})
        base.orders[name] = (up - down) / (math.log(1 + h) - math.log(1 - h))
    return base


# -- Cantera ------------------------------------------------------------------------------------
#
# The export writes an ideal-gas phase of the mechanism's gas components and an ideal-surface phase
# of its adsorbates and free sites. Every reversible step becomes two irreversible reactions with
# the given forward and reverse rate constants, so Cantera's rates do not depend on species
# thermodynamics, which the mechanism does not give: every species gets a zero constant-cp thermo.
# Rate constants go from per site (1/s, pressures in bar) to Cantera's concentrations (kmol, m):
# k = k_site Gamma^(1 - m) for m surface reactants; adsorptions keep their sticking coefficients.
# A gas reactant of a rate constant (a re-adsorption, an Eley-Rideal step) gets (R T / 1e5)^a.

FREE = "free(s)"


def _surface_name(name: str) -> str:
    return FREE if name == SITE else name[:-1] + "(s)"


def _composition(formula: str) -> dict[str, float]:
    atoms = parse_formula(formula)
    if atoms is None:
        raise ValueError(f"no readable formula: {formula!r}")
    return {k: float(v) for k, v in atoms.items()}


def cantera_yaml(mech: Mechanism, formulas: Mapping[str, str], name: str = "mechanism") -> str:
    """The Cantera YAML of *mech*; *formulas*: the gas components' formulas by id."""
    gas = sorted({n for s in mech.steps for n in s.gas()})
    gamma = mech.site_density / 1000.0  # kmol/m2
    elements = sorted(
        {e for n in gas for e in _composition(formulas.get(n, ""))}
        | {e for a in mech.adsorbates for e in _composition(a[:-1])}
    )

    def thermo() -> dict[str, Any]:
        return {"model": "constant-cp", "T0": 298.15, "h0": 0.0, "s0": 0.0, "cp0": 0.0}

    species = [
        {"name": n, "composition": _composition(formulas.get(n, "")), "thermo": thermo()}
        for n in gas
    ]
    species.append({"name": FREE, "composition": {"X": 1.0}, "thermo": thermo()})
    for a in mech.adsorbates:
        species.append(
            {
                "name": _surface_name(a),
                "composition": {**_composition(a[:-1]), "X": 1.0},
                "thermo": thermo(),
            }
        )
    reactions = []

    def equation(sides: list[tuple[str, float]], products: list[tuple[str, float]]) -> str:
        def side(items):
            return " + ".join(
                (f"{v:g} " if v != 1 else "") + (_surface_name(n) if n.endswith(SITE) else n)
                for n, v in items
            )

        return f"{side(sides)} => {side(products)}"

    for step in mech.steps:
        reactants = [(n, -v) for n, v in step.stoichiometry.items() if v < 0]
        products = [(n, v) for n, v in step.stoichiometry.items() if v > 0]
        for direction, (left, right) in (
            ("forward", (reactants, products)),
            ("reverse", (products, reactants)),
        ):
            forward_rate, reverse_rate = step.constants()
            rate = forward_rate if direction == "forward" else reverse_rate
            if direction == "reverse" and rate is None:
                continue
            surface_order = sum(v for n, v in left if n.endswith(SITE))
            entry: dict[str, Any] = {
                "equation": equation(left, right),
                "id": f"{step.id}-{direction}",
            }
            if direction == "forward" and step.sticking is not None:
                entry["sticking-coefficient"] = {
                    "A": step.sticking.s0,
                    "b": 0.0,
                    "Ea": step.sticking.Ea,
                }
            else:
                # per site with pressures in bar -> Cantera's concentrations: k Gamma^(1 - m)
                # for m surface reactants, (R T / 1e5)^a for a gas reactants (p = c R T)
                gas_order = sum(v for n, v in left if not n.endswith(SITE))
                entry["rate-constant"] = {
                    "A": rate.A
                    * rate.T_ref ** (-rate.n)
                    * gamma ** (1 - surface_order)
                    * (R_J * 1000.0 / 1e5) ** gas_order,
                    "b": rate.n + gas_order,
                    "Ea": rate.Ea,
                }
            reactions.append(entry)
    document = {
        "description": f"{name}: exported by cheme-as-code (mean-field mechanism; reversible "
        "steps as two irreversible reactions; thermo not used)",
        "units": {"length": "m", "quantity": "kmol", "activation-energy": "J/mol"},
        "elements": [{"symbol": "X", "atomic-weight": 1.0}],
        "phases": [
            {
                "name": "gas",
                "thermo": "ideal-gas",
                "elements": [*elements, "X"],
                "species": gas,
                "state": {"T": 300.0, "P": 1.0e5},
            },
            {
                "name": "surface",
                "thermo": "ideal-surface",
                "adjacent-phases": ["gas"],
                "elements": [*elements, "X"],
                "species": [FREE, *(_surface_name(a) for a in mech.adsorbates)],
                "kinetics": "surface",
                "reactions": "all",
                "site-density": gamma,
                "state": {"T": 300.0, "coverages": {FREE: 1.0}},
            },
        ],
        "species": species,
        "reactions": reactions,
    }
    return json.dumps(document, indent=2)  # JSON is YAML
