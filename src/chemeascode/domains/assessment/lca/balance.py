"""Balance checks of an LCI dataset: mass, element and energy closure over
its exchanges, and the carbon split by origin.

Two interfaces:

- :func:`element_balance`, the minimal check tiered generation requires: the
  formula of each exchange's component from ``generation.formulas``; the balance is closed when
  every element's in and out agree within ``tolerance`` (the rounding of written amounts).
- :func:`dataset_balance`, the balance gates over any dataset, flowsheet-derived or written by hand.
  Inputs and resources
  (free ones such as air and water included) count in, products, outputs (wastes, by-products) and
  emissions out, per the dataset's basis.

**What takes part.** Material exchanges of the operation in kg, and in Nm3 where their
composition gives the molar mass (ideal gas at 0 degC and 1.01325 bar,
:data:`~chemeascode.foundation.units.MOLAR_VOLUME_NORMAL`). Every other exchange is excluded
with its reason, never silently: its ``balance_exclusion``; another phase (construction,
maintenance, end of life: the plant's materials, not an operating flow); an avoided-production
credit; a vent or intake counted by its ``emission:*`` / ``resource:*`` exchanges; energy (kWh:
the energy closure); and any other unit (ea, tkm, m3, ...: not a mass). Flows recorded as cut
off (``cutoff:``) are listed beside the balance, not counted in it (the cut-off criteria bound
them, :mod:`.cutoff`).

**Composition** (:func:`elements_per_kg`): the exchange's ``composition`` (mass fractions of
components with formulas, or of elements), else its formula in ``generation.formulas``, else
the formula of a common elementary flow by CAS number (:data:`CAS_FORMULAS`). A material
exchange without one makes the element balance *not assessable* (named, never counted as 0).

**Carbon by origin**: the carbon of the inputs split into fossil, biogenic and atmospheric
(direct air capture and the uptake of CO2 from air) by :func:`.carbon.trace`, against the
carbon of the products, emissions and other outputs (wastes). The outputs whose origin is
declared (an emission mapped ``origin: fossil|biogenic``, a declared ``biogenic_fraction``)
must not carry more carbon of an origin than the inputs give.

**Energy** is a closure fraction with its basis, never a pass or fail: electricity, heat and
steam in, and fuels at their lower heating value, against the heat rejected (``cold`` duties),
the energy exported and the energy content of the products (``properties.energy``); the
sensible and latent enthalpy of the material streams is not in the dataset and not counted.

**Tolerances** (:func:`tolerance`): the defaults,
relative to the larger side, 1 % for a dataset derived from a simulated
flowsheet and 5 % for a sourced screening dataset (a Tier 0 or 1 estimate, one written by hand, or a
design of maturity concept or screening). A breach is a warning of ``cheme assess lca`` and fails
the gate requirements ``lci-mass-balance``, ``lci-element-balance`` and ``lci-carbon-origin``
(:mod:`.gates`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.assessment.lca.allocation import _released
from chemeascode.domains.assessment.lca.carbon import CO2_CAS, Load, _stock_change, trace
from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.schemas import (
    ASH,
    COMPOSITION_ROUNDING,
    TIER_MATURITY_CAP,
    CarbonAccounting,
    CarbonContent,
    DatasetExchange,
    ElementBalanceRecord,
    LciDataset,
)
from chemeascode.domains.process.screening_balance import (
    ATOMIC_MASS,
    element_masses,
    molar_mass,
    parse_formula,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.units import MOLAR_VOLUME_NORMAL

#: Relative tolerance of an element's in and out: the rounding of written amounts.
TOLERANCE = 1e-6
SIDES = {"input": "in", "resource": "in", "product": "out", "output": "out", "emission": "out"}


@dataclass
class ElementBalance:
    """kg of each element in and out per the dataset's basis, and what was left out."""

    elements: dict[str, tuple[float, float]] = field(default_factory=dict)
    tolerance: float = TOLERANCE
    outside: list[str] = field(default_factory=list)

    def unbalanced(self) -> dict[str, tuple[float, float]]:
        """The elements whose in and out differ by more than the tolerance."""
        return {
            e: (i, o)
            for e, (i, o) in self.elements.items()
            if abs(i - o) > self.tolerance * max(abs(i), abs(o), 1e-12)
        }

    @property
    def closed(self) -> bool:
        return bool(self.elements) and not self.unbalanced()

    def record(self) -> ElementBalanceRecord:
        return ElementBalanceRecord(
            closed=self.closed,
            tolerance=self.tolerance,
            elements={e: [round(i, 9), round(o, 9)] for e, (i, o) in sorted(self.elements.items())},
            outside=sorted(self.outside),
        )


def element_balance(
    dataset: LciDataset, formulas: dict[str, str] | None = None, tolerance: float = TOLERANCE
) -> ElementBalance:
    """The element balance of *dataset*, with *formulas* (exchange key -> formula) or, by
    default, the dataset's ``generation.formulas``."""
    if formulas is None:
        formulas = dataset.generation.formulas if dataset.generation else {}
    sides: dict[str, dict[str, float]] = {"in": {}, "out": {}}
    outside: list[str] = []
    for exchange in dataset.exchanges:
        if exchange.unit != "kg" or exchange.key not in formulas or exchange.type not in SIDES:
            outside.append(exchange.key)
            continue
        sides[SIDES[exchange.type]][exchange.key] = exchange.amount
    found_in, bad_in = element_masses(sides["in"], formulas)
    found_out, bad_out = element_masses(sides["out"], formulas)
    names = sorted({*found_in, *found_out})
    return ElementBalance(
        elements={e: (found_in.get(e, 0.0), found_out.get(e, 0.0)) for e in names},
        tolerance=tolerance,
        outside=outside + bad_in + bad_out,
    )


# -- the balance gates -----------------------------------------------------------------------------

#: Default tolerances (relative, of the larger side), a design choice: a
#: dataset derived from a simulated flowsheet closes within 1 %, a sourced screening dataset within
#: 5 %.
SIMULATED_TOLERANCE = 0.01
SOURCED_TOLERANCE = 0.05
#: process.yaml maturities whose datasets are screening level (as :data:`.carbon.TOLERANCE`).
SCREENING_MATURITIES = ("concept", "screening")
#: The generator a flowsheet-derived dataset records (``provenance.generator``).
DERIVED = "cheme assess lca"
#: Molecular formulas of common elementary flows by CAS number: what an emission or resource
#: without a composition is made of (NOx is counted as NO2, as its CAS number says).
CAS_FORMULAS: dict[str, str] = {
    "124-38-9": "CO2",
    "630-08-0": "CO",
    "74-82-8": "CH4",
    "7732-18-5": "H2O",
    "7727-37-9": "N2",
    "7782-44-7": "O2",
    "7440-37-1": "Ar",
    "1333-74-0": "H2",
    "7664-41-7": "NH3",
    "10024-97-2": "N2O",
    "10102-43-9": "NO",
    "10102-44-0": "NO2",
    "7446-09-5": "SO2",
    "7783-06-4": "H2S",
    "7647-01-0": "HCl",
    "7782-50-5": "Cl2",
    "67-56-1": "CH4O",
}
#: kWh per MJ.
KWH_PER_MJ = 1 / 3.6
#: The sides of the balance by exchange type.
SIDE = {"input": "in", "resource": "in", "product": "out", "output": "out", "emission": "out"}
#: Rule ids of the findings, by gate requirement.
RULES = {
    "lci-mass-balance": "cheme.lci-mass-balance",
    "lci-element-balance": "cheme.lci-element-balance",
    "lci-carbon-origin": "cheme.lci-carbon-origin",
}


@dataclass
class Closure:
    """One quantity's balance (kg per the dataset's basis): in, out and whether it closes."""

    quantity: str
    inputs: float = 0.0
    outputs: float = 0.0
    tolerance: float = SIMULATED_TOLERANCE

    @property
    def residual(self) -> float:
        """In minus out."""
        return self.inputs - self.outputs

    @property
    def relative(self) -> float:
        """The residual relative to the larger side (0 when nothing flows)."""
        scale = max(abs(self.inputs), abs(self.outputs))
        return self.residual / scale if scale > 0 else 0.0

    @property
    def closed(self) -> bool:
        return abs(self.relative) <= self.tolerance

    def text(self, basis: str) -> str:
        return (
            f"{self.quantity}: in {self.inputs:.6g} kg, out {self.outputs:.6g} kg per {basis}, "
            f"residual {self.residual:+.6g} kg ({self.relative:+.2%}, tolerance "
            f"{self.tolerance:.0%})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "in": round(self.inputs, 9),
            "out": round(self.outputs, 9),
            "residual": round(self.residual, 9),
            "relative": round(self.relative, 6),
            "closed": self.closed,
        }


@dataclass
class CarbonOrigin:
    """The carbon of the inputs by origin against the carbon of the outputs by kind (kg C)."""

    #: fossil, biogenic, atmospheric (direct air capture, uptake of CO2 from air).
    inputs: dict[str, float] = field(default_factory=dict)
    #: products, emissions, outputs (wastes, CO2 to storage, other outputs).
    outputs: dict[str, float] = field(default_factory=dict)
    #: kg C of the outputs whose origin is declared, by origin (fossil, biogenic).
    declared: dict[str, float] = field(default_factory=dict)
    #: The exchanges behind ``declared``.
    declared_by: dict[str, list[str]] = field(default_factory=dict)
    #: Problems tracing the carbon (a referenced dataset that does not load, ...).
    problems: list[str] = field(default_factory=list)
    tolerance: float = SIMULATED_TOLERANCE

    @property
    def closure(self) -> Closure:
        return Closure("C", sum(self.inputs.values()), sum(self.outputs.values()), self.tolerance)

    def available(self, origin: str) -> float:
        """kg C of *origin* the inputs give (biogenic counts the atmospheric carbon too: both
        are non-fossil)."""
        if origin == "fossil":
            return self.inputs.get("fossil", 0.0)
        return self.inputs.get("biogenic", 0.0) + self.inputs.get("atmospheric", 0.0)

    def mismatched(self) -> dict[str, tuple[float, float]]:
        """Origins whose declared outputs carry more carbon than the inputs of that origin give,
        beyond the tolerance of the larger carbon side: origin -> (declared out, available)."""
        scale = max(sum(self.inputs.values()), sum(self.outputs.values()))
        return {
            origin: (out, self.available(origin))
            for origin, out in self.declared.items()
            if out - self.available(origin) > self.tolerance * scale
        }

    @property
    def closed(self) -> bool:
        return self.closure.closed and not self.mismatched()

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit": "kg C",
            "inputs": {k: round(v, 9) for k, v in self.inputs.items()},
            "outputs": {k: round(v, 9) for k, v in self.outputs.items()},
            "declared_outputs": {k: round(v, 9) for k, v in self.declared.items()},
            **self.closure.as_dict(),
            "closed": self.closed,
            "mismatched": sorted(self.mismatched()),
            "problems": list(self.problems),
        }


@dataclass
class EnergyClosure:
    """The energy entering and leaving the dataset (kWh per its basis), by term."""

    inputs: dict[str, float] = field(default_factory=dict)
    outputs: dict[str, float] = field(default_factory=dict)
    #: Energy exchanges whose carrier is unknown (not counted).
    unclassified: list[str] = field(default_factory=list)
    basis: str = (
        "electricity, heat and steam as delivered, fuels at their lower heating value (carrier "
        "lhv), heat rejected (cold duties), energy exported and the products' energy content "
        "(properties.energy); the sensible and latent enthalpy of material streams is not counted"
    )

    @property
    def fraction(self) -> float | None:
        """Energy out over energy in; None when no energy enters."""
        entering = sum(self.inputs.values())
        return sum(self.outputs.values()) / entering if entering > 0 else None

    def as_dict(self) -> dict[str, Any]:
        fraction = self.fraction
        return {
            "unit": "kWh",
            "inputs": {k: round(v, 9) for k, v in self.inputs.items()},
            "outputs": {k: round(v, 9) for k, v in self.outputs.items()},
            "closure": None if fraction is None else round(fraction, 6),
            "unclassified": list(self.unclassified),
            "basis": self.basis,
        }


@dataclass
class DatasetBalance:
    """The mass, element, carbon-origin and energy balance of one dataset."""

    dataset: str
    basis: str
    tolerance: float
    #: Why that tolerance (e.g. maturity screening).
    tolerance_basis: str
    mass: Closure | None = None
    #: Why the mass balance is not assessable (empty when it is).
    mass_unassessable: str = ""
    elements: dict[str, Closure] = field(default_factory=dict)
    #: Material exchanges without a usable composition (the element balance not assessable).
    unknown: dict[str, str] = field(default_factory=dict)
    carbon: CarbonOrigin | None = None
    energy: EnergyClosure = field(default_factory=EnergyClosure)
    #: Exchange key -> why it is outside the mass and element balances.
    excluded: dict[str, str] = field(default_factory=dict)
    #: Cut-off flows (``cutoff:``): key -> (direction, amount or None, unit).
    cutoff: dict[str, tuple[str, float | None, str]] = field(default_factory=dict)

    @property
    def elements_assessable(self) -> bool:
        return not self.unknown and bool(self.elements)

    def unbalanced(self) -> list[Closure]:
        return [c for c in self.elements.values() if not c.closed]

    def status(self, requirement: str) -> tuple[str, list[str]]:
        """``closed``, ``open`` or ``not-assessable`` for a gate *requirement*, and what makes
        it so (each naming its residual)."""
        if requirement == "lci-mass-balance":
            if self.mass is None:
                return "not-assessable", [f"mass balance not assessable: {self.mass_unassessable}"]
            if not self.mass.closed:
                return "open", [f"mass balance does not close: {self.mass.text(self.basis)}"]
            return "closed", []
        if requirement == "lci-element-balance":
            if not self.elements_assessable:
                return "not-assessable", [self._unassessable("element balance")]
            open_ = self.unbalanced()
            return ("open" if open_ else "closed"), [
                f"element balance does not close: {c.text(self.basis)}" for c in open_
            ]
        if requirement == "lci-carbon-origin":
            if self.unknown:
                return "not-assessable", [self._unassessable("carbon balance")]
            carbon = self.carbon
            if carbon is not None and carbon.problems:
                # the origin of some input carbon is not known: no split to compare
                return "not-assessable", [
                    f"carbon balance not assessable: {p}" for p in carbon.problems
                ]
            if carbon is None or not (carbon.closure.inputs or carbon.closure.outputs):
                return "closed", []
            found: list[str] = []
            if not carbon.closure.closed:
                found.append(
                    "carbon of the inputs (fossil "
                    f"{carbon.inputs.get('fossil', 0.0):.6g}, biogenic "
                    f"{carbon.inputs.get('biogenic', 0.0):.6g}, atmospheric "
                    f"{carbon.inputs.get('atmospheric', 0.0):.6g} kg C) does not match the "
                    "products, emissions and wastes ("
                    + ", ".join(f"{k} {v:.6g}" for k, v in carbon.outputs.items())
                    + f" kg C): {carbon.closure.text(self.basis).replace(' kg', ' kg C')}"
                )
            for origin, (out, available) in carbon.mismatched().items():
                keys = ", ".join(carbon.declared_by.get(origin, []))
                found.append(
                    f"outputs declared {origin} ({keys}) carry {out:.6g} kg C per {self.basis}, "
                    f"the inputs give {available:.6g} kg C of {origin} carbon: residual "
                    f"{available - out:+.6g} kg C"
                )
            return ("open" if found else "closed"), found
        raise ValueError(f"unknown balance requirement {requirement}")

    def _unassessable(self, what: str) -> str:
        if not self.elements and not self.unknown:
            return f"{what} not assessable: no material exchange"
        return f"{what} not assessable: no composition for " + ", ".join(
            f"{k} ({why})" for k, why in self.unknown.items()
        )

    def findings(self, file: str) -> list[Finding]:
        """A warning per open balance (rules :data:`RULES`), an info per one not assessable."""
        found: list[Finding] = []
        hints = {
            "lci-mass-balance": "an input or output (a purge, a waste, a free resource such as "
            "air or water) is missing or its amount is wrong",
            "lci-element-balance": "check the compositions and the reaction products; a missing "
            "by-product or emission shows in the element that does not close",
            "lci-carbon-origin": "a carbon output (CO2, CO, CH4, a purge, a waste) or input is "
            "missing, or an emission's origin (fossil or biogenic) does not match the inputs",
        }
        unassessable_hint = (
            "give the exchange a composition (fractions with formulas, or elements), or a "
            "balance_exclusion with the reason"
        )
        for requirement, rule in RULES.items():
            state, problems = self.status(requirement)
            if state == "open":
                found += [
                    Finding(
                        file,
                        "warning",
                        rule,
                        p,
                        ids=[self.dataset],
                        hint=hints[requirement],
                        key=f"{self.dataset}:{n}",
                    )
                    for n, p in enumerate(problems)
                ]
        mass, _ = self.status("lci-mass-balance")
        elements, problems = self.status("lci-element-balance")
        if mass == "not-assessable":
            found.append(
                Finding(
                    file,
                    "info",
                    "cheme.lci-balance-unassessable",
                    f"{self.dataset}: mass balance not assessable: {self.mass_unassessable}",
                    ids=[self.dataset],
                    hint="give the products and the material inputs and outputs in kg",
                )
            )
        if elements == "not-assessable" and self.unknown:
            found.append(
                Finding(
                    file,
                    "info",
                    "cheme.lci-balance-unassessable",
                    f"{self.dataset}: {problems[0]}",
                    ids=sorted(self.unknown),
                    hint=unassessable_hint,
                )
            )
        return found

    def as_dict(self) -> dict[str, Any]:
        """What ``lca/manifest.json`` records (``balance``)."""
        statuses = {r: self.status(r) for r in RULES}
        return {
            "dataset": self.dataset,
            "basis": self.basis,
            "tolerance": self.tolerance,
            "tolerance_basis": self.tolerance_basis,
            "status": {r: s for r, (s, _) in statuses.items()},
            "problems": [p for _, (_, found) in statuses.items() for p in found],
            "mass": {"unit": "kg", **self.mass.as_dict()} if self.mass is not None else None,
            "mass_unassessable": self.mass_unassessable or None,
            "elements": {e: c.as_dict() for e, c in sorted(self.elements.items())},
            "no_composition": dict(sorted(self.unknown.items())),
            "carbon": self.carbon.as_dict() if self.carbon is not None else None,
            "energy": self.energy.as_dict(),
            "excluded": dict(sorted(self.excluded.items())),
            "cutoff": {
                k: {"direction": d, "amount": a, "unit": u}
                for k, (d, a, u) in sorted(self.cutoff.items())
            },
        }


def tolerance(dataset: LciDataset, maturity: str | None = None) -> tuple[float, str]:
    """The default tolerance of *dataset* and why: 5 % for a sourced screening dataset (a
    Tier 0 or 1 estimate, a design of maturity concept or screening, or a dataset not derived
    from a flowsheet), else 1 % (derived from a simulated flowsheet)."""
    generation = dataset.generation
    if generation is not None and generation.tier in TIER_MATURITY_CAP:
        return SOURCED_TOLERANCE, f"Tier {generation.tier} estimate (sourced screening)"
    if maturity in SCREENING_MATURITIES:
        return SOURCED_TOLERANCE, f"design maturity {maturity} (sourced screening)"
    if not dataset.provenance.generator.startswith(DERIVED):
        return SOURCED_TOLERANCE, "not derived from a flowsheet (sourced)"
    return SIMULATED_TOLERANCE, "derived from a simulated flowsheet"


def _parsed(formula: str) -> tuple[dict[str, float], float] | None:
    """kg of each element per kg of *formula*, and its molar mass; None if unreadable."""
    atoms, mass = parse_formula(formula), molar_mass(formula)
    if not atoms or not mass:
        return None
    return {e: n * ATOMIC_MASS[e] / mass for e, n in atoms.items()}, mass


def elements_per_kg(
    exchange: DatasetExchange, formulas: dict[str, str] | None = None
) -> tuple[dict[str, float] | None, float | None, str]:
    """kg of each element per kg of *exchange*, its mean molar mass (kg/kmol, None when not
    known) and, when the elements are not known, why. *formulas* is exchange key -> formula
    (``generation.formulas``)."""
    composition = exchange.composition
    if composition is not None and composition.elements:
        total = sum(composition.elements.values())
        if total < 1 - COMPOSITION_ROUNDING:
            return None, None, f"its elements cover {total:.4%} of its mass"
        # ash is mass without an element of the balance (the ultimate analysis' residue)
        return {e: v for e, v in composition.elements.items() if e != ASH}, None, ""
    if composition is not None:
        total = sum(composition.fractions.values())
        if total < 1 - COMPOSITION_ROUNDING:
            return None, None, f"its composition covers {total:.4%} of its mass"
        found: dict[str, float] = {}
        moles = 0.0
        for component, fraction in composition.fractions.items():
            formula = composition.formulas.get(component, component)
            parsed = _parsed(formula)
            if parsed is None:
                return None, None, f"no readable formula for {component}"
            per_kg, mass = parsed
            moles += fraction / mass
            for element, share in per_kg.items():
                found[element] = found.get(element, 0.0) + fraction * share
        return found, (total / moles if moles > 0 else None), ""
    formula = (formulas or {}).get(exchange.key) or CAS_FORMULAS.get(
        normalise_cas(exchange.cas or "")
    )
    if formula:
        parsed = _parsed(formula)
        if parsed is not None:
            return parsed[0], parsed[1], ""
        return None, None, f"no readable formula {formula}"
    return None, None, "no composition"


def _exclusion(exchange: DatasetExchange) -> str:
    """Why *exchange* is outside the mass and element balances; empty when it takes part."""
    if exchange.balance_exclusion:
        return exchange.balance_exclusion
    if exchange.phase != "operation":
        return f"{exchange.phase} phase: not an operating flow"
    if exchange.key.startswith("avoided:"):
        return "avoided production: a credit, not a physical flow"
    if _stock_change(exchange):
        return "land-use change: carbon from soil and biomass stocks, not an operating flow"
    if _released(exchange):
        return "counted by its emission:* or resource:* exchanges"
    if exchange.unit == "kWh":
        return "energy: in the energy closure"
    if exchange.unit == "m3" and _water(exchange):
        return ""
    if exchange.unit not in ("kg", "Nm3"):
        return f"unit {exchange.unit}: not a mass"
    return ""


#: kg per m3 of water, the convention by which a water flow in m3 enters the mass balance
#: (LCI databases count water by volume at 1000 kg/m3).
WATER_DENSITY = 1000.0
WATER_CAS = "7732-18-5"


def _water(exchange: DatasetExchange) -> bool:
    """A water flow by its CAS number (7732-18-5)."""
    return normalise_cas(exchange.cas or "") == WATER_CAS


def _energy(dataset: LciDataset, masses: dict[str, float] | None = None) -> EnergyClosure:
    """The energy closure; *masses* (kg by key) converts a fuel in Nm3 to its LHV basis."""
    found = EnergyClosure()

    def add(side: dict[str, float], term: str, kwh: float) -> None:
        side[term] = side.get(term, 0.0) + kwh

    for exchange in dataset.exchanges:
        if exchange.phase != "operation" or exchange.key.startswith("avoided:"):
            continue
        side = SIDE.get(exchange.type)
        carrier = exchange.carrier
        if exchange.unit == "kWh":
            if carrier is None:
                found.unclassified.append(exchange.key)
            elif carrier.kind == "cold":
                # cold delivered to the plant is heat taken out of it: heat rejected
                add(
                    found.outputs if side == "in" else found.inputs,
                    "heat rejected",
                    exchange.amount,
                )
            elif side == "in":
                add(found.inputs, carrier.kind, exchange.amount)
            else:
                add(found.outputs, f"{carrier.kind} exported", exchange.amount)
        elif exchange.unit in ("kg", "Nm3") and carrier is not None:
            kg = exchange.amount if exchange.unit == "kg" else (masses or {}).get(exchange.key)
            if kg is None and exchange.unit == "Nm3":
                # a fuel outside the mass balance (balance_exclusion) still has a molar mass
                molar = elements_per_kg(exchange)[1]
                kg = exchange.amount / MOLAR_VOLUME_NORMAL * molar if molar else None
            if carrier.lhv is None or kg is None:
                # a fuel without its LHV, or a gas without its molar mass: never counted as 0
                found.unclassified.append(exchange.key)
                continue
            kwh = kg * carrier.lhv * KWH_PER_MJ
            add(found.inputs if side == "in" else found.outputs, "fuel (LHV)", kwh)
        elif (
            exchange.type == "product"
            and exchange.properties is not None
            and exchange.properties.energy is not None
        ):
            # properties.energy is kJ per unit of the product
            add(
                found.outputs,
                "products (energy content)",
                exchange.amount * exchange.properties.energy / 3600,
            )
    return found


def _carbon(
    dataset: LciDataset,
    per_kg: dict[str, dict[str, float]],
    masses: dict[str, float],
    excluded: dict[str, str],
    tolerance_: float,
    accounting: CarbonAccounting | None,
    load: Load | None,
    path: str,
) -> CarbonOrigin:
    """The carbon by origin, traced by :func:`.carbon.trace` over the exchanges in the balance,
    each given the carbon its composition holds (where it states none) and its mass in kg."""
    exchanges = []
    for exchange in dataset.exchanges:
        if exchange.key in excluded:
            continue
        update: dict[str, Any] = {}
        if exchange.unit in ("Nm3", "m3") and exchange.key in masses:
            update.update(unit="kg", amount=masses[exchange.key])
        given = exchange.carbon.total if exchange.carbon is not None else None
        if given is None and exchange.key in per_kg:
            content = exchange.carbon or CarbonContent()
            update["carbon"] = content.model_copy(
                update={"total": per_kg[exchange.key].get("C", 0.0)}
            )
        exchanges.append(exchange.model_copy(update=update) if update else exchange)
    traced = trace(dataset.model_copy(update={"exchanges": exchanges}), accounting, load, path)
    found = CarbonOrigin(tolerance=tolerance_, problems=list(traced.problems))
    by_key = {e.key: e for e in exchanges}
    for flow in traced.flows:
        exchange = by_key[flow.key]
        if SIDE[flow.type] == "in":
            if exchange.type == "resource" and normalise_cas(exchange.cas or "") == CO2_CAS:
                # CO2 taken from air: atmospheric carbon, whatever fraction it declares
                found.inputs["atmospheric"] = found.inputs.get("atmospheric", 0.0) + flow.carbon
                continue
            atmospheric = flow.how == "uptake" or flow.how.startswith(
                "co2-source direct-air-capture"
            )
            origin = "atmospheric" if atmospheric else "biogenic"
            found.inputs["fossil"] = found.inputs.get("fossil", 0.0) + flow.carbon - flow.biogenic
            found.inputs[origin] = found.inputs.get(origin, 0.0) + flow.biogenic
            continue
        kind = {"product": "products", "emission": "emissions"}.get(flow.type, "outputs")
        found.outputs[kind] = found.outputs.get(kind, 0.0) + flow.carbon
        fraction = exchange.carbon.biogenic_fraction if exchange.carbon is not None else None
        spec = exchange.link.elementary if exchange.link is not None else None
        if fraction is None and spec is not None and spec.origin in ("fossil", "biogenic"):
            fraction = 0.0 if spec.origin == "fossil" else 1.0
        if fraction is None:
            continue  # undeclared: takes the pool's traced fraction, consistent by construction
        for origin, share in (("fossil", 1 - fraction), ("biogenic", fraction)):
            if share > 0:
                found.declared[origin] = found.declared.get(origin, 0.0) + flow.carbon * share
                found.declared_by.setdefault(origin, []).append(flow.key)
    found.inputs = {o: found.inputs.get(o, 0.0) for o in ("fossil", "biogenic", "atmospheric")}
    return found


def dataset_balance(
    dataset: LciDataset,
    maturity: str | None = None,
    accounting: CarbonAccounting | None = None,
    load: Load | None = None,
    path: str = "",
    tolerance_: float | None = None,
) -> DatasetBalance:
    """The mass, element, carbon-origin and energy balance of *dataset*, at
    the default :func:`tolerance` for a design of *maturity* (process.yaml) unless *tolerance_* is
    given. *accounting* and *load* are passed to :func:`.carbon.trace` (the CCU rule, datasets
    that inputs reference)."""
    default, why = tolerance(dataset, maturity)
    if tolerance_ is not None:
        default, why = tolerance_, "given"
    found = DatasetBalance(dataset.id, dataset.basis, default, why)
    formulas = dataset.generation.formulas if dataset.generation else {}
    sides: dict[str, float] = {"in": 0.0, "out": 0.0}
    elements: dict[str, list[float]] = {}
    per_kg: dict[str, dict[str, float]] = {}
    masses: dict[str, float] = {}
    no_mass: list[str] = []
    uncounted_m3 = [
        e.key
        for e in dataset.exchanges
        if e.unit == "m3" and _exclusion(e).startswith("unit m3") and SIDE.get(e.type)
    ]
    for exchange in dataset.exchanges:
        side = SIDE.get(exchange.type)
        why_out = _exclusion(exchange)
        if not why_out and exchange.unit == "m3" and uncounted_m3:
            # water in m3 beside an m3 flow not counted (a wastewater return without a CAS
            # number): counting one side only would open the balance
            why_out = (
                "water in m3 beside m3 flows not counted ("
                + ", ".join(uncounted_m3)
                + "): give them their CAS number, or both a balance_exclusion"
            )
        if why_out or side is None:
            found.excluded[exchange.key] = why_out or f"type {exchange.type}"
            continue
        shares, molar, why_unknown = elements_per_kg(exchange, formulas)
        mass: float | None = exchange.amount
        if exchange.unit == "Nm3":
            mass = exchange.amount / MOLAR_VOLUME_NORMAL * molar if molar else None
        elif exchange.unit == "m3":
            mass = exchange.amount * WATER_DENSITY
        if mass is None:
            no_mass.append(exchange.key)
            found.unknown[exchange.key] = why_unknown or "Nm3 without the molar mass"
            continue
        masses[exchange.key] = mass
        sides[side] += mass
        if shares is None:
            found.unknown[exchange.key] = why_unknown
            continue
        per_kg[exchange.key] = shares
        for element, share in shares.items():
            pair = elements.setdefault(element, [0.0, 0.0])
            pair[0 if side == "in" else 1] += mass * share
    for flow in dataset.cutoff:
        found.cutoff[flow.key] = (flow.direction, flow.amount, flow.unit)
    if no_mass:
        found.mass_unassessable = "no mass for " + ", ".join(no_mass)
    elif sides["in"] <= 0 and sides["out"] <= 0:
        found.mass_unassessable = "no material exchange in kg"
    else:
        found.mass = Closure("mass", sides["in"], sides["out"], default)
    found.elements = {e: Closure(e, i, o, default) for e, (i, o) in sorted(elements.items())}
    found.carbon = _carbon(dataset, per_kg, masses, found.excluded, default, accounting, load, path)
    found.energy = _energy(dataset, masses)
    return found


def _percent(closure: Closure) -> str:
    return f"{closure.relative:+.2%}"


def summary(found: DatasetBalance) -> str:
    """One line per gate requirement and the energy closure (``cheme assess lca --coverage``)."""
    parts = []
    for requirement in RULES:
        state, _ = found.status(requirement)
        parts.append(f"{requirement.removeprefix('lci-')} {state}")
    fraction = found.energy.fraction
    energy = "not assessable" if fraction is None else f"{fraction:.1%}"
    return (
        f"balance ({found.tolerance:.0%} tolerance, {found.tolerance_basis}): "
        + ", ".join(parts)
        + f"; energy closure {energy}"
    )


def text(found: DatasetBalance) -> str:
    """The balance as a table (``cheme assess lca --balance``): closure per quantity and
    element, residuals in kg per basis and %, the carbon by origin, the energy closure and the
    exchanges excluded with their reasons."""
    lines = [
        f"Balance of {found.dataset} per {found.basis} (tolerance {found.tolerance:.0%}: "
        f"{found.tolerance_basis})",
        "",
        f"{'quantity':<10} {'in, kg':>14} {'out, kg':>14} {'residual, kg':>14} {'%':>9}  status",
    ]

    def row(closure: Closure) -> str:
        return (
            f"{closure.quantity:<10} {closure.inputs:>14.6g} {closure.outputs:>14.6g} "
            f"{closure.residual:>+14.6g} {_percent(closure):>9}  "
            + ("closed" if closure.closed else "OPEN")
        )

    if found.mass is not None:
        lines.append(row(found.mass))
    else:
        lines.append(f"{'mass':<10} not assessable: {found.mass_unassessable}")
    for closure in found.elements.values():
        lines.append(row(closure))
    if found.unknown:
        lines.append("element balance not assessable, no composition:")
        lines += [f"  {k}: {why}" for k, why in found.unknown.items()]
    carbon = found.carbon
    if carbon is not None and (carbon.closure.inputs or carbon.closure.outputs):
        lines += [
            "",
            "carbon, kg C: in "
            + ", ".join(f"{k} {v:.6g}" for k, v in carbon.inputs.items())
            + "; out "
            + ", ".join(f"{k} {v:.6g}" for k, v in carbon.outputs.items()),
        ]
        if carbon.declared:
            lines.append(
                "  outputs of declared origin: "
                + ", ".join(f"{k} {v:.6g}" for k, v in carbon.declared.items())
            )
        lines += [f"  trace: {p}" for p in carbon.problems]
    energy = found.energy
    fraction = energy.fraction
    lines += [
        "",
        "energy, kWh: in "
        + (", ".join(f"{k} {v:.6g}" for k, v in energy.inputs.items()) or "none counted")
        + "; out "
        + (", ".join(f"{k} {v:.6g}" for k, v in energy.outputs.items()) or "none counted")
        + "; closure "
        + ("not assessable" if fraction is None else f"{fraction:.1%}"),
        f"  basis: {energy.basis}",
    ]
    if energy.unclassified:
        lines.append(f"  without a carrier (not counted): {', '.join(energy.unclassified)}")
    if found.excluded:
        lines += ["", "excluded:"]
        lines += [f"  {k}: {why}" for k, why in found.excluded.items()]
    if found.cutoff:
        lines += ["", "cut off (listed, not counted):"]
        lines += [
            f"  {k} ({d}): " + ("amount unknown" if a is None else f"{a:.6g} {u}")
            for k, (d, a, u) in found.cutoff.items()
        ]
    problems = [p for r in RULES for p in found.status(r)[1]]
    if problems:
        lines += ["", "problems:"] + [f"  {p}" for p in problems]
    return "\n".join(lines) + "\n"
