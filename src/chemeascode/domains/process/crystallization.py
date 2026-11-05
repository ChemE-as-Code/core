"""A crystallizer and a filter or centrifuge: the bounded solid-liquid adapter.

One solute crystallizes from one solvent, as an anhydrous crystal or a hydrate (the crystal's
formula is the solute's plus n solvent, e.g. ``Na2CO3(H2O)10`` from ``Na2CO3`` and ``H2O``), in a
block or step with a ``crystallizer:`` (schema :class:`~.schema.Crystallizer`), from one or more
material inlets taken together. The train is, in this order: the feed joined by the recycled
mother liquor, evaporation of solvent (optional), crystallization at the crystallizer's
temperature, a filter or centrifuge (optional) that sends the crystals with the liquid the cake
holds to the cake, and the filtrate divided into the recycle and the purge (``mother_liquor``).
The model:

- **basis: solubility** (predictive within the solubility data): the mother liquor leaves
  saturated at the crystallizer's temperature, so the crystals are what the solute and solvent
  balances leave above the solubility, with the hydrate's water taken from the solvent:
  ``C = (S - s W) / (a - s (1 - a))`` (S anhydrous solute, W solvent, s kg solute per kg
  solvent, a the crystal's anhydrous solute mass fraction). An undersaturated feed gives no
  crystals. Solubility points are interpolated linearly in temperature and never extrapolated;
- **basis: yield** (specified): the fraction of the solute entering that crystallizes is
  imposed. With solubility data as well, an imposed yield beyond the equilibrium yield is
  reported (the liquor would be below its solubility);
- the filter or centrifuge is always specified: solid recovery and the liquid held in the cake
  (``solid_separation:`` alone: the same, for any slurry); the recycle is a fraction of the
  filtrate, solved by successive substitution;
- the energy balance (with ``energy:``) is lumped over the whole train: the fresh feed's
  sensible heat from its temperature to the crystallizer's (constant heat capacity), the heat of
  crystallization of the crystals formed and the latent heat of the solvent evaporated, every
  outlet at the crystallizer's temperature: ``Q = F cp (T - T_feed) + C dH_cryst + E lambda``
  (several inlets: their mass-weighted mean temperature, exact for one heat capacity);
- **a mixed liquor** (``spectators:``, ADR 0056): other dissolved components (a salt, a base,
  unreacted reagent) pass with the liquor unchanged, never crystallizing or evaporating. The
  solubility then holds in that liquor: measured in it (``measured_in: mother_liquor``; per kg
  of solvent, per kg of solute-free liquor ``L = W + P`` (P the spectators), or as the solute's
  mass fraction in the saturated liquor, which is ``x / (1 - x)`` per kg of L), so that
  ``C = (S - s (W + P)) / (a - s (1 - a))``; or the pure solvent's corrected by Setschenow
  coefficients, ``log10(s0 / s) = sum k_i m_i`` with ``m_i`` the spectator's molality in the
  mother liquor (mol per kg of free solvent; with a hydrate solved by successive substitution,
  the hydrate's water leaving the liquor). A pure-solvent solubility alone is refused;
- **a reslurry wash** is a crystallizer fed by the cake and the wash liquid (two inlets): the
  crystals dissolve until the liquid is saturated (all of them when it stays undersaturated),
  followed by its own or a separate filter.

Not modelled (and so never claimed): supersaturation, nucleation and growth kinetics, crystal
size distribution (no population balance), several crystallizing solutes, a spectator's own
solubility limit, common-ion effects beyond the declared data, electrolyte activity models,
solid solutions, polymorph or hydrate transitions (one crystal form, the one declared),
displacement washing, the evaporator's own solubility limit, heats of dilution, filtration or
centrifuge rates.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from chemeascode.domains.chemistry.formulas import ATOMIC_MASS, parse_formula
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import PLANT_FILE, NotAPlantRepository
from chemeascode.foundation.yamlsource import _yaml_line

REPORT_INPUTS = (MATERIALS_FILE, FLOWSHEET_FILE, PLANT_FILE)

#: What the crystallizer model assumes (listed with its model basis).
ASSUMPTIONS = (
    "steady state",
    "solid-liquid equilibrium at the crystallizer's temperature (basis: solubility): no "
    "supersaturation remains, the residence time suffices",
    "one solute in one solvent, one crystal form (anhydrous or the declared hydrate)",
    "no population balance: crystal size, shape and their effect on the cake are not modelled",
    "filter or centrifuge specified: solid recovery and cake liquid given, the liquid divides "
    "with one composition between cake and filtrate (no washing)",
)
#: What the crystallizer assumes besides, with spectator solutes (ADR 0056).
LIQUOR_ASSUMPTIONS = (
    "spectator solutes stay dissolved and non-volatile: they leave with the liquor unchanged and "
    "their own solubility limit is not checked",
    "the solute's solubility in the mixed liquor from data measured in it or from Setschenow "
    "salting-out coefficients on the molal scale (no electrolyte activity model)",
)
#: What a filter or centrifuge on its own assumes.
SEPARATION_ASSUMPTIONS = (
    "steady state",
    "solid recovery and cake liquid specified (no filtration or centrifuge model)",
    "the liquid divides with one composition between cake and filtrate (no washing)",
)
#: Relative tolerance of the recycle loop, on the fresh feed's mass flow.
RECYCLE_TOLERANCE = 1e-10
MAX_ITERATIONS = 200_000
#: The salting-out correction with a hydrate: successive substitution on the free solvent.
SALTING_TOLERANCE = 1e-13
SALTING_ITERATIONS = 1000


class CrystallizationError(ValueError):
    """The crystallizer or separator cannot be solved as declared."""


class Unsupported(CrystallizationError):
    """The case is outside what the model represents (several solutes, extrapolation, ...)."""


# -- the crystal --------------------------------------------------------------------------------


@dataclass(frozen=True)
class CrystalForm:
    """The crystal against its solute and solvent: ``hydrate`` solvent molecules per crystal."""

    solute_molar_mass: float
    solvent_molar_mass: float
    crystal_molar_mass: float
    hydrate: float
    atoms: dict[str, dict[str, int]]  # role -> atoms per element

    @property
    def solute_fraction(self) -> float:
        """kg of anhydrous solute per kg of crystal (a)."""
        return self.solute_molar_mass / self.crystal_molar_mass


def crystal_form(solute: str, solvent: str, crystal: str) -> CrystalForm:
    """The crystal form from the three formulas; CrystallizationError unless the crystal is the
    solute plus a non-negative number of solvent molecules."""
    atoms = {"solute": parse_formula(solute), "solvent": parse_formula(solvent)}
    atoms["crystal"] = parse_formula(crystal)
    unreadable = [
        f"{r} {f!r}" for r, f in zip(atoms, (solute, solvent, crystal), strict=True) if not atoms[r]
    ]
    if unreadable:
        raise CrystallizationError(
            "no readable formula for the " + ", ".join(unreadable) + " (write e.g. MgSO4(H2O)7)"
        )
    a, w, c = (atoms[r] or {} for r in ("solute", "solvent", "crystal"))
    extra = {e: c.get(e, 0) - a.get(e, 0) for e in {*a, *c}}
    ratios = {extra.get(e, 0) / n for e, n in w.items()}
    if (
        any(v < 0 for v in extra.values())
        or len(ratios) != 1
        or any(extra[e] and e not in w for e in extra)
    ):
        raise CrystallizationError(
            f"the crystal {crystal} is not the solute {solute} plus n {solvent}"
        )
    n = ratios.pop()

    def mass(atoms_of: dict[str, int]) -> float:
        return sum(ATOMIC_MASS[e] * k for e, k in atoms_of.items())

    return CrystalForm(mass(a), mass(w), mass(c), n, {r: dict(v or {}) for r, v in atoms.items()})


# -- the streams of the train -------------------------------------------------------------------


@dataclass(frozen=True)
class Slurry:
    """kg/h of dissolved (anhydrous) solute, free solvent and crystals, and of each spectator
    solute (dissolved, carried unchanged)."""

    solute: float = 0.0
    solvent: float = 0.0
    crystal: float = 0.0
    spectators: dict[str, float] = field(default_factory=dict)

    @property
    def others(self) -> float:
        """kg/h of the spectator solutes together (P)."""
        return sum(self.spectators.values())

    @property
    def total(self) -> float:
        return self.solute + self.solvent + self.crystal + self.others

    @property
    def liquid(self) -> float:
        return self.solute + self.solvent + self.others

    def __add__(self, other: Slurry) -> Slurry:
        names = dict.fromkeys([*self.spectators, *other.spectators])
        return Slurry(
            self.solute + other.solute,
            self.solvent + other.solvent,
            self.crystal + other.crystal,
            {n: self.spectators.get(n, 0.0) + other.spectators.get(n, 0.0) for n in names},
        )

    def scaled(self, factor: float) -> Slurry:
        return Slurry(
            self.solute * factor,
            self.solvent * factor,
            self.crystal * factor,
            {n: v * factor for n, v in self.spectators.items()},
        )

    def distance(self, other: Slurry) -> float:
        names = {*self.spectators, *other.spectators}
        return max(
            abs(self.solute - other.solute),
            abs(self.solvent - other.solvent),
            abs(self.crystal - other.crystal),
            *(abs(self.spectators.get(n, 0.0) - other.spectators.get(n, 0.0)) for n in names),
        )

    def entry(self) -> dict[str, Any]:
        """As the report gives it (``spectators`` only when there are any)."""
        found = asdict(self) | {"total": self.total}
        if not self.spectators:
            del found["spectators"]
        return found


@dataclass(frozen=True)
class Liquor:
    """The spectator solutes of a crystallizer's mother liquor (ADR 0056): their molar masses
    (kg/kmol) and atoms, what the solubility is per kg of (``solvent``, or ``liquor``: solvent
    plus spectators) and the Setschenow coefficients (log10 basis, kg/mol) that correct a
    pure-solvent solubility for them."""

    molar_mass: dict[str, float]
    atoms: dict[str, dict[str, int]] = field(default_factory=dict)
    basis: Literal["solvent", "liquor"] = "solvent"
    salting_out: dict[str, float] = field(default_factory=dict)

    def salting_mass(self, spectators: dict[str, float]) -> float:
        """kg/h: ``sum_i k_i n_i`` (n_i in mol/h), so that the exponent is this over the free
        solvent in kg/h."""
        return sum(
            k * 1000.0 * spectators.get(n, 0.0) / self.molar_mass[n]
            for n, k in self.salting_out.items()
        )

    def molality(self, spectators: dict[str, float], free_solvent: float) -> dict[str, float]:
        """mol per kg of free solvent of each spectator."""
        if free_solvent <= 0:
            return dict.fromkeys(spectators, math.inf)
        return {n: 1000.0 * v / self.molar_mass[n] / free_solvent for n, v in spectators.items()}


def solubility_at(spec: Any, temperature: float | None) -> float:
    """kg of anhydrous solute per kg of solvent from a :class:`~.schema.Solubility` at
    *temperature* (K); Unsupported outside the points' range."""
    if spec.value is not None:
        value = spec.value
    else:
        points = spec.points
        low, high = points[0][0], points[-1][0]
        if temperature is None:
            raise CrystallizationError("solubility points need the crystallizer's temperature")
        if not low - 1e-9 <= temperature <= high + 1e-9:
            raise Unsupported(
                f"the crystallizer's temperature {temperature:g} K is outside the solubility "
                f"data ({low:g}-{high:g} K): no extrapolation"
            )
        value = points[-1][1]
        for (t0, v0), (t1, v1) in zip(points, points[1:], strict=False):
            if t0 <= temperature <= t1:
                value = v0 + (v1 - v0) * (temperature - t0) / (t1 - t0)
                break
        if len(points) == 1:
            value = points[0][1]
    return value / (1.0 - value) if spec.unit == "mass_fraction" else value


@dataclass
class Stage:
    """One pass through evaporation and crystallization."""

    vapour: float
    slurry: Slurry
    #: Crystals formed at equilibrium (None without solubility data).
    equilibrium_crystal: float | None
    undersaturated: bool = False
    #: kg/kg (the solubility's basis): the solubility in the mother liquor at the solution (the
    #: declared one, or the salting-out corrected one).
    solubility: float | None = None


def _evaporated(feed: Slurry, evaporation: Any) -> float:
    if evaporation is None:
        return 0.0
    if evaporation.flow is not None:
        removed = evaporation.flow
    elif evaporation.feed_fraction is not None:
        removed = evaporation.feed_fraction * feed.total
    elif evaporation.solvent_fraction is not None:
        removed = evaporation.solvent_fraction * feed.solvent
    else:
        x = evaporation.concentration
        if feed.solute <= 0:
            raise CrystallizationError("evaporation to a concentration: the feed holds no solute")
        removed = feed.solvent - (feed.solute * (1.0 - x) / x - feed.others)
        if removed < -1e-9 * max(feed.total, 1.0):
            raise CrystallizationError(
                f"evaporation: the feed's liquid already holds more than {x:g} solute "
                f"({feed.solute / feed.liquid:.4g})"
            )
        removed = max(removed, 0.0)
    if removed > feed.solvent * (1 + 1e-12):
        raise CrystallizationError(
            f"evaporation removes {removed:.6g} kg/h, more than the {feed.solvent:.6g} kg/h of "
            "solvent fed"
        )
    return removed


def _equilibrium(
    solute: float,
    solvent: float,
    spectators: dict[str, float],
    a: float,
    solubility: float,
    liquor: Liquor | None,
) -> tuple[float, float]:
    """(crystals at equilibrium, kg/h, negative when undersaturated; the solubility in the
    mother liquor) for *solute* (anhydrous, dissolved and as crystals) and *solvent* (free and
    in the crystals): ``C = (S - s (W + beta P)) / (a - s (1 - a))``, beta 1 when the solubility
    is per kg of solute-free liquor. A salting-out correction makes ``s`` depend on the free
    solvent the hydrate leaves, solved by successive substitution."""
    per_liquor = liquor is not None and liquor.basis == "liquor"
    base = solvent + (sum(spectators.values()) if per_liquor else 0.0)
    salting = liquor.salting_mass(spectators) if liquor is not None else 0.0
    free = solvent
    for _ in range(SALTING_ITERATIONS):
        if salting and free <= 0:
            raise CrystallizationError("the mother liquor holds no free solvent")
        s = solubility * 10.0 ** (-salting / free) if salting else solubility
        denominator = a - s * (1.0 - a)
        if denominator <= 0:
            raise CrystallizationError(
                f"the crystal holds less solute ({a:.4g} kg/kg) than the saturated liquor: it "
                "cannot crystallize from it at this solubility"
            )
        crystal = (solute - s * base) / denominator
        if not salting or a >= 1.0:
            return crystal, s
        new = solvent - (1.0 - a) * max(crystal, 0.0)
        if abs(new - free) <= SALTING_TOLERANCE * max(solvent, 1e-9):
            return crystal, s
        free = new
    raise CrystallizationError(
        f"the salting-out correction did not converge in {SALTING_ITERATIONS} iterations"
    )


def crystallize(
    feed: Slurry,
    form: CrystalForm,
    *,
    solubility: float | None = None,
    imposed_yield: float | None = None,
    evaporation: Any = None,
    liquor: Liquor | None = None,
) -> Stage:
    """Evaporation, then crystallization: by *solubility* (kg/kg solvent, or per kg of
    solute-free liquor and corrected for salting-out as *liquor* says; the yield follows) or
    by *imposed_yield* (the fraction of the entering anhydrous solute, dissolved or as crystals,
    that leaves as crystals). Both given: the yield is imposed, the solubility only compared.
    The feed's spectators pass unchanged."""
    if solubility is None and imposed_yield is None:
        raise CrystallizationError("neither a solubility nor an imposed yield")
    removed = _evaporated(feed, evaporation)
    a = form.solute_fraction
    solute = feed.solute + a * feed.crystal
    solvent = feed.solvent - removed + (1.0 - a) * feed.crystal
    equilibrium = None
    undersaturated = False
    effective = None
    if solubility is not None:
        equilibrium, effective = _equilibrium(
            solute, solvent, feed.spectators, a, solubility, liquor
        )
        undersaturated = equilibrium < 0
        equilibrium = max(equilibrium, 0.0)
    crystal = imposed_yield * solute / a if imposed_yield is not None else equilibrium
    assert crystal is not None
    slurry = Slurry(
        solute - a * crystal, solvent - (1.0 - a) * crystal, crystal, dict(feed.spectators)
    )
    if slurry.solvent < -1e-9 * max(feed.total, 1.0):
        raise CrystallizationError(
            "the imposed yield binds more solvent in the hydrate than the liquor holds"
        )
    return Stage(removed, slurry, equilibrium, undersaturated, effective)


def cake_liquid_of(solid: float, cake_liquid: Any) -> float:
    """kg/h of liquid held by a cake of *solid* kg/h (:class:`~.schema.CakeLiquid`)."""
    if cake_liquid.basis == "per_kg_solid":
        return cake_liquid.value * solid
    return cake_liquid.value / (1.0 - cake_liquid.value) * solid


def separate_solids(
    mass: dict[str, float], solids: set[str], recovery: float, cake_liquid: Any
) -> tuple[dict[str, float], dict[str, float]]:
    """(cake, filtrate) kg/h by component: *recovery* of every solid component to the cake with
    the liquid it holds, the liquid divided with one composition; CrystallizationError when the
    cake would hold more liquid than there is."""
    solid = {n: v for n, v in mass.items() if n in solids}
    liquid = {n: v for n, v in mass.items() if n not in solids}
    to_cake = recovery * sum(solid.values())
    held = cake_liquid_of(to_cake, cake_liquid)
    available = sum(liquid.values())
    if held > available * (1 + 1e-12) + 1e-12:
        raise CrystallizationError(
            f"the cake holds {held:.6g} kg/h of liquid, the slurry has {available:.6g} kg/h"
        )
    share = min(held / available, 1.0) if available > 0 else 0.0
    cake = {n: v * recovery for n, v in solid.items()} | {n: v * share for n, v in liquid.items()}
    filtrate = {n: v - cake[n] for n, v in mass.items()}
    return cake, filtrate


def _separate(slurry: Slurry, separation: Any) -> tuple[Slurry, Slurry]:
    mass = {"solute": slurry.solute, "solvent": slurry.solvent, "crystal": slurry.crystal}
    mass |= {f"spectator:{n}": v for n, v in slurry.spectators.items()}
    cake, filtrate = separate_solids(
        mass, {"crystal"}, separation.solid_recovery, separation.cake_liquid
    )

    def rebuilt(part: dict[str, float]) -> Slurry:
        return Slurry(
            part["solute"],
            part["solvent"],
            part["crystal"],
            {n: part[f"spectator:{n}"] for n in slurry.spectators},
        )

    return rebuilt(cake), rebuilt(filtrate)


@dataclass
class TrainResult:
    """The solved train: its streams (kg/h), yields, balances and energy."""

    streams: dict[str, Slurry]
    form: CrystalForm
    basis: str
    #: kg/kg of free solvent: the declared solubility, or with spectators the mother liquor's
    #: at the solution (per kg of solvent, salting out applied).
    solubility: float | None
    temperature: float | None
    crystals_formed: float
    equilibrium_crystals: float | None
    undersaturated: bool
    iterations: int
    loop_residual: float
    #: Anhydrous solute in the cake's crystals over the solute in the fresh feed.
    recovery: float | None
    #: The same with the solute dissolved in the cake's liquid (a dried product).
    product_recovery: float | None
    balances: dict[str, Any] = field(default_factory=dict)
    energy: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    #: With spectator solutes: the mother liquor's solubility basis, the declared value and
    #: its value at the solution in that basis (``solubility`` above is then the mother
    #: liquor's per kg of free solvent), the salting-out factor and the spectators' molality
    #: (ADR 0056); None for one solute in one solvent.
    liquor: dict[str, Any] | None = None

    def entry(self) -> dict[str, Any]:
        found = {
            "basis": self.basis,
            "temperature_K": self.temperature,
            "solubility_kg_per_kg_solvent": self.solubility,
            "hydrate_solvent_per_crystal": self.form.hydrate,
            "crystal_solute_mass_fraction": self.form.solute_fraction,
            "crystals_formed_kg_h": self.crystals_formed,
            "equilibrium_crystals_kg_h": self.equilibrium_crystals,
            "undersaturated": self.undersaturated,
            "recovery": self.recovery,
            "product_recovery": self.product_recovery,
            "iterations": self.iterations,
            "loop_residual_kg_h": self.loop_residual,
            "streams": {k: v.entry() for k, v in self.streams.items()},
            "balances": self.balances,
            "energy": self.energy,
            "notes": self.notes,
        }
        if self.liquor is not None:
            found["mother_liquor"] = self.liquor
        return found


def solve_train(
    feed: Slurry,
    form: CrystalForm,
    *,
    solubility: float | None = None,
    imposed_yield: float | None = None,
    evaporation: Any = None,
    separation: Any = None,
    recycle: float = 0.0,
    temperature: float | None = None,
    energy: Any = None,
    feed_temperature: float | None = None,
    liquor: Liquor | None = None,
) -> TrainResult:
    """The whole train for the fresh *feed*; see the module docstring. *recycle* is the
    fraction of the filtrate returned to the feed (needs *separation*); *liquor* describes the
    feed's spectator solutes (needed when it has any)."""
    if feed.spectators and liquor is None:
        raise CrystallizationError("spectator solutes need their liquor data (Liquor)")
    if recycle and separation is None:
        raise CrystallizationError("a recycle needs a filter or centrifuge (separation)")
    tolerance = RECYCLE_TOLERANCE * max(feed.total, 1e-9)
    returned = Slurry()
    stage: Stage | None = None
    cake = filtrate = Slurry()
    residual = 0.0
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS + 1):  # noqa: B007 (reported)
        stage = crystallize(
            feed + returned,
            form,
            solubility=solubility,
            imposed_yield=imposed_yield,
            evaporation=evaporation,
            liquor=liquor,
        )
        if separation is None:
            break
        cake, filtrate = _separate(stage.slurry, separation)
        new = filtrate.scaled(recycle)
        residual = new.distance(returned)
        returned = new
        if residual <= tolerance or not recycle:
            break
        if returned.total > 1e3 * max(feed.total, 1e-9):
            raise CrystallizationError(
                "the recycle grows without bound (beyond 1000 times the feed): nothing leaves the "
                "loop at steady state (no crystals form and no purge)"
            )
    else:
        raise CrystallizationError(
            f"the recycle did not converge in {MAX_ITERATIONS} iterations "
            f"(last change {residual:.3g} kg/h)"
        )
    assert stage is not None
    vapour = Slurry(solvent=stage.vapour)
    streams: dict[str, Slurry] = {"feed": feed}
    if separation is not None:
        # the loop's last pass: recycle, crystallizer feed and slurry agree to the tolerance
        purge = filtrate.scaled(1.0 - recycle)
        streams |= {
            "recycle": filtrate.scaled(recycle),
            # the fresh feed with the recycle, before evaporation
            "combined_feed": feed + filtrate.scaled(recycle),
            "vapour": vapour,
            "slurry": stage.slurry,
            "cake": cake,
            "filtrate": filtrate,
            "mother_liquor": purge,
        }
        outlets = {"vapour": vapour, "cake": cake, "mother_liquor": purge}
    else:
        streams |= {"vapour": vapour, "slurry": stage.slurry}
        outlets = {"vapour": vapour, "slurry": stage.slurry}
    a = form.solute_fraction
    fed = feed.solute + a * feed.crystal
    leaving = sum(s.crystal for s in outlets.values())
    result = TrainResult(
        streams=streams,
        form=form,
        basis="solubility" if imposed_yield is None else "yield",
        solubility=solubility,
        temperature=temperature,
        crystals_formed=leaving - feed.crystal,
        equilibrium_crystals=stage.equilibrium_crystal,
        undersaturated=stage.undersaturated,
        iterations=iterations,
        loop_residual=residual,
        recovery=(a * cake.crystal / fed if fed > 0 else None) if separation else None,
        product_recovery=(
            ((a * cake.crystal + cake.solute) / fed if fed > 0 else None) if separation else None
        ),
    )
    if stage.undersaturated:
        result.notes.append(
            "undersaturated at the crystallizer's temperature: no crystals form (basis: solubility)"
        )
    if (
        imposed_yield is not None
        and stage.equilibrium_crystal is not None
        and stage.slurry.crystal > stage.equilibrium_crystal * (1 + 1e-6) + 1e-9
    ):
        result.notes.append(
            f"the imposed yield gives {stage.slurry.crystal:.6g} kg/h of crystals, more than the "
            f"{stage.equilibrium_crystal:.6g} kg/h at equilibrium: the liquor would be below its "
            "solubility"
        )
    result.balances = train_balances(feed, outlets, form, liquor)
    if feed.spectators and liquor is not None:
        ml = stage.slurry
        free = ml.solvent
        # the report's solubility_kg_per_kg_solvent: the mother liquor's at the solution, per kg
        # of free solvent (the declared value may be per kg of liquor, or before salting out)
        per_solvent = stage.solubility
        if per_solvent is not None and liquor.basis == "liquor":
            others = sum(ml.spectators.values())
            per_solvent = per_solvent * (free + others) / free if free > 0 else None
        result.solubility = per_solvent
        result.liquor = {
            "spectators": sorted(feed.spectators),
            "solubility_basis": "kg/kg_liquor" if liquor.basis == "liquor" else "kg/kg_solvent",
            "declared_solubility": solubility,
            "solubility": stage.solubility,
            "salting_out_factor": (
                stage.solubility / solubility
                if liquor.salting_out and solubility and stage.solubility is not None
                else None
            ),
            "molality_mol_per_kg_solvent": liquor.molality(ml.spectators, free),
            "solute_mass_fraction": ml.solute / ml.liquid if ml.liquid > 0 else None,
        }
    if energy is not None:
        result.energy = energy_balance(
            feed, stage.vapour, result.crystals_formed, energy, temperature, feed_temperature
        )
    return result


def train_balances(
    feed: Slurry, outlets: dict[str, Slurry], form: CrystalForm, liquor: Liquor | None = None
) -> dict[str, Any]:
    """Mass, anhydrous solute, total solvent (with the hydrate's), each spectator and elements,
    fresh feed against the outlets, as (in, out, residual) in kg/h (elements: kmol/h)."""
    a = form.solute_fraction

    def triple(x: float, y: float) -> dict[str, float]:
        return {"in": x, "out": y, "residual": y - x}

    out = list(outlets.values())

    def elements(s: Slurry) -> dict[str, float]:
        found: dict[str, float] = {}
        for role, kg, mw in (
            ("solute", s.solute, form.solute_molar_mass),
            ("solvent", s.solvent, form.solvent_molar_mass),
            ("crystal", s.crystal, form.crystal_molar_mass),
        ):
            for element, n in form.atoms[role].items():
                found[element] = found.get(element, 0.0) + kg / mw * n
        if liquor is not None:
            for name, kg in s.spectators.items():
                for element, n in liquor.atoms.get(name, {}).items():
                    found[element] = found.get(element, 0.0) + kg / liquor.molar_mass[name] * n
        return found

    e_in = elements(feed)
    e_out: dict[str, float] = {}
    for s in out:
        for k, v in elements(s).items():
            e_out[k] = e_out.get(k, 0.0) + v
    found = {
        "mass": triple(feed.total, sum(s.total for s in out)),
        "solute": triple(
            feed.solute + a * feed.crystal, sum(s.solute + a * s.crystal for s in out)
        ),
        "solvent": triple(
            feed.solvent + (1 - a) * feed.crystal,
            sum(s.solvent + (1 - a) * s.crystal for s in out),
        ),
        "elements_kmol_h": {
            e: triple(e_in.get(e, 0.0), e_out.get(e, 0.0)) for e in sorted({*e_in, *e_out})
        },
    }
    if feed.spectators:
        found["spectators"] = {
            n: triple(v, sum(s.spectators.get(n, 0.0) for s in out))
            for n, v in sorted(feed.spectators.items())
        }
    return found


def energy_balance(
    feed: Slurry,
    evaporated: float,
    crystals: float,
    data: Any,
    temperature: float | None,
    feed_temperature: float | None,
) -> dict[str, Any]:
    """The lumped duty (kW, positive added): every term, or what is missing."""
    missing = []
    t_feed = data.feed_temperature or feed_temperature
    if temperature is None:
        missing.append("the crystallizer's temperature")
    if t_feed is None:
        missing.append("the feed temperature (energy.feed_temperature or the inlet's)")
    if evaporated > 0 and data.latent_heat is None:
        missing.append("energy.latent_heat (solvent is evaporated)")
    if missing:
        return {"duty_kW": None, "missing": missing}
    assert temperature is not None and t_feed is not None
    sensible = feed.total * data.heat_capacity * (temperature - t_feed)  # kJ/h
    crystallization = crystals * data.heat_of_crystallization
    evaporation = evaporated * (data.latent_heat or 0.0)
    total = sensible + crystallization + evaporation
    return {
        "duty_kW": total / 3600.0,
        "duty_kJ_h": total,
        "sensible_kJ_h": sensible,
        "crystallization_kJ_h": crystallization,
        "evaporation_kJ_h": evaporation,
        "feed_temperature_K": t_feed,
        "temperature_K": temperature,
        "missing": [],
        "basis": "lumped over the train: constant heat capacity of the feed solution, heat of "
        "crystallization at the crystallizer's temperature, latent heat of the solvent; every "
        "outlet at the crystallizer's temperature; heats of dilution and the vapour's sensible "
        "heat not included",
    }


# -- the flowsheet: a block or step with crystallizer: or solid_separation: ---------------------


def _inlet_mass(process: Any, inlet: Any, case: str) -> dict[str, float]:
    from chemeascode.domains.process.model import stream_flows

    flows = stream_flows(process, inlet, case)
    if flows.components is None:
        raise CrystallizationError(
            f"inlet {inlet.id}: no flow per component ({', '.join(flows.missing)})"
        )
    return flows.components


def _temperature_of(process: Any, stream: Any, case: str) -> float | None:
    from chemeascode.foundation.units import to_kelvin

    state = stream.state.get(case)
    q = getattr(state, "temperature", None)
    if q is None:
        return None
    return to_kelvin(q.value, q.unit or process.flowsheet.units.temperature)


def _inlets(inlet: Any) -> list[Any]:
    return list(inlet) if isinstance(inlet, list | tuple) else [inlet]


def node_feed(process: Any, spec: Any, inlet: Any, case: str) -> Slurry:
    """The crystallizer's fresh feed from its inlet stream (or streams, taken together);
    Unsupported for a component other than its solute, solvent, crystal and spectators."""
    feed = Slurry()
    for stream in _inlets(inlet):
        mass = _inlet_mass(process, stream, case)
        known = {spec.solute, spec.solvent, spec.crystal, *spec.spectators}
        others = sorted(n for n, v in mass.items() if v and n not in known)
        if others:
            raise Unsupported(
                f"inlet {stream.id} holds {', '.join(others)}: the crystallizer models one "
                f"solute ({spec.solute}) in one solvent ({spec.solvent}); impurities and several "
                "solutes are not modelled unless declared as spectators: (dissolved, carried "
                "unchanged, with a solubility measured in that liquor or a salting_out:)"
            )
        feed = feed + Slurry(
            mass.get(spec.solute, 0.0),
            mass.get(spec.solvent, 0.0),
            mass.get(spec.crystal, 0.0),
            {n: mass.get(n, 0.0) for n in spec.spectators},
        )
    return feed


def _molar_mass(component: Any) -> float | None:
    from chemeascode.domains.chemistry.formulas import molar_mass

    if component.molar_mass:
        return component.molar_mass
    return molar_mass(component.formula) if component.formula else None


def liquor_of(process: Any, spec: Any) -> Liquor | None:
    """The crystallizer's :class:`Liquor` (None without spectators); CrystallizationError when a
    spectator is not a component or has no molar mass."""
    if not spec.spectators:
        return None
    comps = process.components()
    lacking = [n for n in spec.spectators if n not in comps]
    if lacking:
        raise CrystallizationError("spectators not in materials.yaml: " + ", ".join(lacking))
    masses = {n: _molar_mass(comps[n]) for n in spec.spectators}
    if unknown := [n for n, m in masses.items() if not m]:
        raise CrystallizationError(
            "no molar mass (molar_mass or formula) of the spectators " + ", ".join(unknown)
        )
    sol = spec.solubility
    per_liquor = (
        sol is not None and sol.measured_in == "mother_liquor" and sol.unit != "kg/kg_solvent"
    )
    salting = sol.salting_out if sol is not None else None
    factor = 1.0 / math.log(10.0) if salting is not None and salting.log == "ln" else 1.0
    return Liquor(
        molar_mass={n: m for n, m in masses.items() if m},
        atoms={n: dict(parse_formula(comps[n].formula) or {}) for n in spec.spectators},
        basis="liquor" if per_liquor else "solvent",
        salting_out={n: k * factor for n, k in (salting.coefficients if salting else {}).items()},
    )


def pure_solvent_only(spec: Any) -> bool:
    """Whether the crystallizer's solubility is a pure-solvent value although it declares
    spectators (refused: no silent pure-solvent value in a mixed liquor)."""
    sol = spec.solubility
    return bool(
        spec.spectators
        and sol is not None
        and sol.measured_in == "pure_solvent"
        and sol.salting_out is None
    )


def _feed_temperature(process: Any, inlets: list[Any], case: str) -> float | None:
    """K: the one inlet's temperature, or the mass-weighted mean of several (None when one is
    not known)."""
    if len(inlets) == 1:
        return _temperature_of(process, inlets[0], case)
    weighted = total = 0.0
    for stream in inlets:
        t = _temperature_of(process, stream, case)
        if t is None:
            return None
        kg = sum(_inlet_mass(process, stream, case).values())
        weighted += kg * t
        total += kg
    return weighted / total if total > 0 else None


def form_of(process: Any, spec: Any) -> CrystalForm:
    comps = process.components()
    lacking = [n for n in (spec.solute, spec.solvent, spec.crystal) if n not in comps]
    if lacking:
        raise CrystallizationError("components not in materials.yaml: " + ", ".join(lacking))
    return crystal_form(*(comps[n].formula for n in (spec.solute, spec.solvent, spec.crystal)))


def solve_node(process: Any, node: Any, inlet: Any, case: str) -> tuple[TrainResult, dict]:
    """The train of crystallizer *node* fed by stream *inlet* (or a list of streams, taken
    together) in *case*, and what its solution depends on besides the inlets (for the outlets'
    fingerprints)."""
    spec = node.crystallizer
    form = form_of(process, spec)
    inlets = _inlets(inlet)
    feed = node_feed(process, spec, inlets, case)
    liquor = liquor_of(process, spec)
    if feed.others > 0 and pure_solvent_only(spec):
        raise Unsupported(
            f"the solubility of {spec.solute} is the pure solvent's, the liquor holds "
            + ", ".join(n for n, v in feed.spectators.items() if v)
            + ": no pure-solvent value in a mixed liquor (give data measured_in: mother_liquor "
            "or salting_out: coefficients)"
        )
    solubility = (
        solubility_at(spec.solubility, spec.temperature) if spec.solubility is not None else None
    )
    imposed = spec.yield_.value if spec.basis == "yield" and spec.yield_ else None
    result = solve_train(
        feed,
        form,
        solubility=solubility,
        imposed_yield=imposed,
        evaporation=spec.evaporation,
        separation=spec.separation,
        recycle=spec.recycle.fraction if spec.recycle is not None else 0.0,
        temperature=spec.temperature,
        energy=spec.energy,
        feed_temperature=_feed_temperature(process, inlets, case),
        liquor=liquor,
    )
    formulas = {n: process.components()[n].formula for n in (spec.solute, spec.solvent)}
    formulas[spec.crystal] = process.components()[spec.crystal].formula
    for name in spec.spectators:  # none for one solute in one solvent: the fingerprint stays
        formulas[name] = process.components()[name].formula
    return result, {"crystallizer": spec.model_dump(mode="json"), "formulas": formulas}


def node_outlets(spec: Any, result: TrainResult) -> dict[str, dict[str, float]]:
    """Outlet port -> kg/h by component (solute, solvent, crystal ids)."""
    found = {}
    for role, port in spec.outlets.items():
        s = result.streams[role]
        found[port] = {spec.solute: s.solute, spec.solvent: s.solvent, spec.crystal: s.crystal}
        found[port] |= {n: s.spectators.get(n, 0.0) for n in spec.spectators}
        if role == "vapour":
            found[port] = {spec.solvent: s.solvent}
    return found


def outlet_shape(spec: Any, role: str, result: TrainResult) -> dict[str, float]:
    """A composition for an outlet without flow (a vapour of nothing, a purge of nothing)."""
    if role == "vapour":
        return {spec.solvent: 1.0}
    source = result.streams.get("filtrate") or result.streams["slurry"]
    if role in ("cake",):
        return {spec.crystal: 1.0}
    liquid = source.liquid or 1.0
    shape = {spec.solute: source.solute / liquid, spec.solvent: source.solvent / liquid}
    return shape | {n: source.spectators.get(n, 0.0) / liquid for n in spec.spectators}


def separate_node(
    process: Any, node: Any, inlet: Any, case: str
) -> tuple[dict[str, dict[str, float]], dict]:
    """Outlet port -> kg/h by component of filter or centrifuge *node* (``solid_separation:``)
    fed by *inlet*; CrystallizationError when the inlet holds no solid component."""
    from chemeascode.domains.process.solids import solid_components

    spec = node.solid_separation
    mass = _inlet_mass(process, inlet, case)
    solids = solid_components(process)
    if not any(v for n, v in mass.items() if n in solids):
        raise CrystallizationError(
            f"inlet {inlet.id} holds no solid component (phase: solid in materials.yaml)"
        )
    cake, filtrate = separate_solids(mass, solids, spec.solid_recovery, spec.cake_liquid)
    return (
        {spec.outlets["cake"]: cake, spec.outlets["filtrate"]: filtrate},
        {"solid_separation": spec.model_dump(mode="json"), "solids": sorted(solids)},
    )


# -- rules (cheme validate) ---------------------------------------------------------------------


def _material_ports(node: Any, direction: str) -> list[str]:
    return [p.id for p in node.ports if p.direction == direction and p.kind == "material"]


def rules(process: Any) -> list[Finding]:
    """``cheme.process-crystallizer``, ``cheme.process-solid-separation`` and
    ``cheme.process-solid`` findings: references, ports and solubility ranges, and solid
    components in streams that are said to be one fluid phase."""
    from chemeascode.domains.process.solids import solid_components

    findings: list[Finding] = []
    fs = process.flowsheet
    doc = process.flowsheet_doc
    comps = process.components()
    solids = solid_components(process)

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        findings.append(
            Finding(
                FLOWSHEET_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
        spec = node.crystallizer
        loc = [key, index, "crystallizer"]
        outs = _material_ports(node, "out")
        if spec is not None:
            for name in ("solute", "solvent", "crystal"):
                cid = getattr(spec, name)
                if cid not in comps:
                    add(
                        "error",
                        "crystallizer",
                        f"{node.id}: crystallizer {name} {cid!r} is not a component",
                        [*loc, name],
                        [node.id],
                        f"declare {cid} in process/materials.yaml",
                    )
                elif (name == "crystal") != (cid in solids):
                    add(
                        "error",
                        "crystallizer",
                        f"{node.id}: crystallizer {name} {cid} "
                        + ("must be" if name == "crystal" else "must not be")
                        + " a solid component",
                        [*loc, name],
                        [node.id],
                        "phase: solid in materials.yaml marks the crystal, and only it",
                    )
            if all(getattr(spec, n) in comps for n in ("solute", "solvent", "crystal")):
                try:
                    form_of(process, spec)
                except CrystallizationError as failure:
                    add(
                        "error",
                        "crystallizer",
                        f"{node.id}: {failure}",
                        loc,
                        [node.id],
                        "give each component a formula; a hydrate's is the solute's plus n "
                        "solvent, e.g. Na2CO3(H2O)10",
                    )
            mapped = list(spec.outlets.values())
            wrong = sorted(set(mapped) - set(outs))
            unmapped = sorted(set(outs) - set(mapped))
            if wrong or unmapped or len(set(mapped)) != len(mapped):
                add(
                    "error",
                    "crystallizer",
                    f"{node.id}: crystallizer outlets must name each material outlet port once"
                    + (f"; not outlet ports: {', '.join(wrong)}" if wrong else "")
                    + (f"; not named: {', '.join(unmapped)}" if unmapped else ""),
                    [*loc, "outlets"],
                    [node.id],
                    "outlets: {cake: PORT, mother_liquor: PORT, vapour: PORT} or {slurry: PORT}",
                )
            if not _material_ports(node, "in"):
                add(
                    "error",
                    "crystallizer",
                    f"{node.id}: a crystallizer takes at least one material inlet",
                    [key, index, "ports"],
                    [node.id],
                    "give it an inlet port (its inlets are taken together, e.g. a cake and "
                    "its reslurry wash)",
                )
            for i, name in enumerate(spec.spectators):
                if name not in comps:
                    problem = "is not a component"
                elif name in solids:
                    problem = "is a solid component (a spectator stays dissolved)"
                else:
                    continue
                add(
                    "error",
                    "crystallizer",
                    f"{node.id}: crystallizer spectator {name!r} {problem}",
                    [*loc, "spectators", i],
                    [node.id],
                    "spectators are dissolved components of materials.yaml, not phase: solid",
                )
            if pure_solvent_only(spec):
                add(
                    "error",
                    "crystallizer",
                    f"{node.id}: the solubility of {spec.solute} is the pure solvent's, but the "
                    f"mother liquor holds the spectators {', '.join(spec.spectators)}",
                    [*loc, "solubility"],
                    [node.id],
                    "give solubility data measured in that liquor (measured_in: mother_liquor) "
                    "or salting_out: {coefficients: {SPECTATOR: k}} (Setschenow, kg/mol), "
                    "each with its source",
                )
            sol = spec.solubility
            if sol is not None and sol.points and spec.temperature is not None:
                low, high = sol.points[0][0], sol.points[-1][0]
                if not low <= spec.temperature <= high:
                    add(
                        "error",
                        "crystallizer",
                        f"{node.id}: temperature {spec.temperature:g} K is outside the "
                        f"solubility data ({low:g}-{high:g} K)",
                        [*loc, "temperature"],
                        [node.id],
                        "add solubility points that bracket the temperature: no extrapolation",
                    )
            parts = [
                (part.rstrip("_"), getattr(spec, part), [*loc, part.rstrip("_")])
                for part in (
                    "solubility",
                    "yield_",
                    "separation",
                    "recycle",
                    "energy",
                    "evaporation",
                )
            ]
            if sol is not None and sol.salting_out is not None:
                parts.append(("salting_out", sol.salting_out, [*loc, "solubility", "salting_out"]))
            for what, value, where in parts:
                if value is not None and value.provenance == "given" and not value.source.strip():
                    add(
                        "warning",
                        "crystallizer",
                        f"{node.id}: crystallizer {what} is given without a source",
                        where,
                        [node.id],
                        "give the source (handbook table, paper, vendor test)",
                    )
        sep = node.solid_separation
        if sep is not None:
            mapped = list(sep.outlets.values())
            if sorted(mapped) != sorted(outs) or len(set(mapped)) != 2:
                add(
                    "error",
                    "solid-separation",
                    f"{node.id}: solid_separation outlets must be its two material outlet ports",
                    [key, index, "solid_separation", "outlets"],
                    [node.id],
                    "outlets: {cake: PORT, filtrate: PORT}",
                )
            if len(_material_ports(node, "in")) != 1:
                add(
                    "error",
                    "solid-separation",
                    f"{node.id}: a filter or centrifuge takes one material inlet",
                    [key, index, "ports"],
                    [node.id],
                    "mix the feeds in a Mixing step before it",
                )
            if sep.provenance == "given" and not sep.source.strip():
                add(
                    "warning",
                    "solid-separation",
                    f"{node.id}: solid_separation is given without a source",
                    [key, index, "solid_separation"],
                    [node.id],
                    "give the source of the recovery and cake liquid (vendor or pilot test)",
                )
    for i, stream in enumerate(fs.streams):
        for case, state in stream.state.items():
            phase, comp = state.phase, state.composition
            if phase is None or comp is None or phase.value != "vapor":
                continue
            held = sorted(n for n, v in comp.values.items() if v and n in solids)
            if held:
                add(
                    "error",
                    "solid",
                    f"stream {stream.id} ({case}): phase vapor but it holds the solid "
                    + ", ".join(held),
                    ["streams", i, "state", case, "phase"],
                    [stream.id],
                    "remove the phase (a slurry has no single fluid phase) or the solid",
                )
    return findings


# -- the report: cheme process crystallizers ----------------------------------------------------


class UnknownCase(ValueError):
    """The case asked for is not declared in the flowsheet."""


@dataclass
class CrystallizerReport:
    root: Path
    case: str | None
    process: Any
    findings: list[Finding] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def loaded(self) -> bool:
        return self.process is not None and not any(f.level == "error" for f in self.findings)

    def to_json(self) -> str:
        return json.dumps(
            {
                "case": self.case,
                "units": self.units,
                "findings": [{**asdict(f), "id": f.id} for f in self.findings],
                "source": self.source.as_dict(),
            },
            indent=2,
        )


def _slurry_entries(
    process: Any, ports: dict[str, dict[str, float]], volatiles: list[str] | None = None
) -> dict[str, Any]:
    """Outlet port -> its dry solid and liquid: the solid components and the rest, or for a
    dryer (*volatiles*) its own split, the volatiles the liquid and everything else the dry
    solid (what the cake liquid held dissolved is dried onto the crystals), so that the
    product's moisture is the dryer's."""
    from chemeascode.domains.process.solids import divide, solid_components

    if volatiles is None:
        solids = solid_components(process)
        return {port: divide(port, mass, solids).entry() for port, mass in ports.items()}
    return {
        port: divide(port, mass, {n for n in mass if n not in volatiles}).entry()
        for port, mass in ports.items()
    }


def _flowsheet_outlets(process: Any, node: Any, case: str) -> dict[str, Any]:
    """Outlet port -> its stream (the flowsheet's)."""
    found = {}
    for stream in process.flowsheet.streams:
        start, _ = process.ends(stream)
        if start is not None and start.node == node.id and stream.kind == "material":
            found[start.port] = stream
    return found


def _compare(process: Any, node: Any, case: str, ports: dict[str, dict[str, float]]) -> list[str]:
    """Where the flowsheet's given or assumed outlet values differ from the model's, beyond the
    flowsheet's tolerance (values propagate wrote are the model's and not compared)."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.domains.process.propagate import ours

    tol = process.flowsheet.tolerance
    differ = []
    for port, stream in _flowsheet_outlets(process, node, case).items():
        state = stream.state.get(case)
        if state is None or ours(state.flow) or ours(state.composition):
            continue
        flows = stream_flows(process, stream, case)
        model = ports.get(port, {})
        if flows.total is None:
            continue
        names = set(model) | set(flows.components or {})
        pairs = [("flow", flows.total, sum(model.values()))]
        if flows.components is not None:
            pairs += [(n, flows.components.get(n, 0.0), model.get(n, 0.0)) for n in sorted(names)]
        for what, given, calc in pairs:
            if abs(given - calc) > tol.abs + tol.rel * max(abs(given), abs(calc)):
                differ.append(f"{stream.id} {what}: {given:.6g} kg/h written, {calc:.6g} model")
    return differ


def _inlet(process: Any, node: Any) -> Any:
    """The material inlet stream of a filter (one), or a crystallizer's inlet streams (a
    list, at least one)."""
    ins = [
        s
        for s in process.flowsheet.streams
        if s.kind == "material" and (end := process.ends(s)[1]) is not None and end.node == node.id
    ]
    if node.crystallizer is not None:
        if not ins:
            raise CrystallizationError("no material inlet stream")
        return ins
    if len(ins) != 1:
        raise CrystallizationError(f"{len(ins)} material inlet streams, one needed")
    return ins[0]


def unit_entry(process: Any, node: Any, case: str) -> dict[str, Any]:
    """One crystallizer, filter or dryer in *case*: its basis, solution, outlets as dry solid
    and liquid, balances, energy, assumptions and limitations (or the reason it is not solved).
    A dryer's heating stream that differs from its duty is in ``duty_differences``."""
    from chemeascode.domains.process.model_basis import solids_basis

    basis = solids_basis(process, node)
    model = (
        "crystallizer"
        if node.crystallizer is not None
        else "dryer"
        if node.dryer is not None
        else "solid_separation"
    )
    entry: dict[str, Any] = {
        "node": node.id,
        "model": model,
        "basis": basis.basis,
        "predictive": basis.predictive,
        "sourced": basis.sourced,
        "detail": basis.detail,
        "sources": basis.sources,
        "assumptions": basis.assumptions,
        "limitations": basis.limitations,
        "solution": None,
        "outlets": {},
        "differences": [],
        "duty_differences": [],
        "problem": None,
        "unsupported": False,
    }
    try:
        inlet = _inlet(process, node)
        if node.dryer is not None:
            from chemeascode.domains.process.dryer import DryerError, dryer_entry

            try:
                ports, entry["solution"], differ = dryer_entry(process, node, inlet, case)
            except DryerError as failure:
                raise CrystallizationError(str(failure)) from failure
            entry["duty_differences"] = differ
        elif node.crystallizer is not None:
            result, _ = solve_node(process, node, inlet, case)
            ports = node_outlets(node.crystallizer, result)
            entry["solution"] = result.entry()
        else:
            ports, _ = separate_node(process, node, inlet, case)
        volatiles = list(node.dryer.volatiles) if node.dryer is not None else None
        entry["outlets"] = _slurry_entries(process, ports, volatiles)
        entry["differences"] = _compare(process, node, case, ports)
    except CrystallizationError as failure:
        entry["problem"] = str(failure)
        entry["unsupported"] = isinstance(failure, Unsupported)
    return entry


def crystallizer_report(root: Path, case: str | None = None) -> CrystallizerReport:
    """Every crystallizer, filter or centrifuge and dryer (``crystallizer:``,
    ``solid_separation:``, ``dryer:``) of the plant repository at *root* in *case* (default:
    the default case). Raises
    :class:`NotAPlantRepository` and :class:`UnknownCase`; a process that does not load is
    reported through ``findings``."""
    from chemeascode.domains.process.model import load

    root = Path(root)
    if not (root / PLANT_FILE).is_file():
        raise NotAPlantRepository(f"No {PLANT_FILE} in {root}.")
    source = source_revision(root, REPORT_INPUTS)
    process, findings = load(root)
    report = CrystallizerReport(root, None, process, findings, source=source)
    if not report.loaded:
        return report
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        raise UnknownCase(f"unknown case {case!r}")
    report.case = case
    fs = process.flowsheet
    keys = {n.id: ("steps", i) for i, n in enumerate(fs.steps)}
    keys |= {n.id: ("blocks", i) for i, n in enumerate(fs.blocks)}
    for node in [*fs.blocks, *fs.steps]:
        if node.crystallizer is None and node.solid_separation is None and node.dryer is None:
            continue
        entry = unit_entry(process, node, case)
        report.units.append(entry)
        loc = list(keys[node.id])
        if entry["problem"]:
            report.findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "error",
                    "cheme.process-crystallizer-unsupported"
                    if entry["unsupported"]
                    else "cheme.process-crystallizer-unsolved",
                    f"{node.id} ({case}): {entry['problem']}",
                    line=_yaml_line(process.flowsheet_doc, loc),
                    ids=[node.id],
                    hint="the case is outside the model's scope: represent it with stream "
                    "values or a component_separator with a sourced split"
                    if entry["unsupported"]
                    else "correct the specification or the inlet",
                )
            )
        for text in entry["differences"]:
            report.findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "warning",
                    "cheme.process-crystallizer-outlet",
                    f"{node.id} ({case}): {text}",
                    line=_yaml_line(process.flowsheet_doc, loc),
                    ids=[node.id],
                    hint="let cheme process propagate --fill write the outlets, or correct "
                    "the specification",
                )
            )
        for text in entry["duty_differences"]:
            report.findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "warning",
                    "cheme.process-dryer-duty",
                    f"{node.id} ({case}): {text}",
                    line=_yaml_line(process.flowsheet_doc, [*loc, "dryer", "energy"]),
                    ids=[node.id],
                    hint="write the model's duty on the heating stream, or correct dryer.energy "
                    "(heat capacity, latent heats, efficiency)",
                )
            )
        for note in (entry["solution"] or {}).get("notes", []):
            report.findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "warning" if "imposed yield" in note else "info",
                    "cheme.process-crystallizer-yield",
                    f"{node.id} ({case}): {note}",
                    line=_yaml_line(process.flowsheet_doc, loc),
                    ids=[node.id],
                    hint="check the yield against the solubility data and their sources",
                )
            )
    return report


def report_text(report: CrystallizerReport) -> str:
    """The report as ``cheme process crystallizers`` prints it."""

    def num(v: float | None, unit: str = "", fmt: str = ".6g") -> str:
        return "?" if v is None else f"{v:{fmt}}{unit}"

    lines = []
    for u in report.units:
        kind = "predictive" if u["predictive"] else "specified"
        lines.append(
            f"{u['model']} {u['node']}: basis {u['basis']} ({kind}"
            + (", sourced" if u["sourced"] else ", not sourced")
            + f"); {u['detail']}"
        )
        if u["problem"]:
            lines.append(f"  not solved: {u['problem']}")
        sol = u["solution"]
        if sol and u["model"] == "dryer":
            from chemeascode.domains.process.dryer import solution_lines

            lines += solution_lines(sol)
        elif sol:
            lines.append(
                f"  crystals formed {num(sol['crystals_formed_kg_h'], ' kg/h')}"
                + (
                    f" (equilibrium {num(sol['equilibrium_crystals_kg_h'], ' kg/h')})"
                    if sol["equilibrium_crystals_kg_h"] is not None
                    else ""
                )
                + f", recovery {num(sol['recovery'], fmt='.4g')}"
                + f", loop iterations {sol['iterations']}"
            )
            b = sol["balances"]
            lines.append(
                f"  balances: mass residual {b['mass']['residual']:.3g} kg/h, solute "
                f"{b['solute']['residual']:.3g} kg/h, elements max "
                + num(
                    max((abs(e["residual"]) for e in b["elements_kmol_h"].values()), default=0.0),
                    " kmol/h",
                    ".3g",
                )
            )
            if ml := sol.get("mother_liquor"):
                factor = ml.get("salting_out_factor")
                declared = num(ml.get("declared_solubility"), fmt=".4g")
                lines.append(
                    f"  mother liquor: solubility {num(ml['solubility'], fmt='.4g')} "
                    f"{ml['solubility_basis']} (declared {declared}"
                    + (f", salting-out factor {factor:.4g}" if factor is not None else "")
                    + f"), {num(sol['solubility_kg_per_kg_solvent'], fmt='.4g')} kg/kg_solvent"
                )
                spectators = b.get("spectators") or {}
                molality = ml.get("molality_mol_per_kg_solvent") or {}
                lines.append(
                    "  spectators: "
                    + ", ".join(
                        f"{n} {num(molality.get(n), ' mol/kg', '.4g')}" for n in ml["spectators"]
                    )
                    + "; max residual "
                    + num(
                        max((abs(v["residual"]) for v in spectators.values()), default=0.0),
                        " kg/h",
                        ".3g",
                    )
                )
            energy = sol["energy"]
            if energy:
                if energy["duty_kW"] is None:
                    lines.append("  energy: missing " + "; ".join(energy["missing"]))
                else:
                    lines.append(
                        f"  duty {energy['duty_kW']:.6g} kW (sensible "
                        f"{energy['sensible_kJ_h']:.6g}, crystallization "
                        f"{energy['crystallization_kJ_h']:.6g}, evaporation "
                        f"{energy['evaporation_kJ_h']:.6g} kJ/h)"
                    )
        for port, o in u["outlets"].items():
            moisture = o["moisture_mass_fraction"]
            lines.append(
                f"  {port}: {o['total_kg_h']:.6g} kg/h, dry solid {o['dry_solid_kg_h']:.6g}, "
                f"liquid {o['liquid_kg_h']:.6g}"
                + (f", moisture {moisture:.4g}" if o["dry_solid_kg_h"] > 0 else "")
            )
        for text in u["differences"] + u.get("duty_differences", []):
            lines.append(f"  differs: {text}")
    if not report.units:
        lines.append(
            "no crystallizer, solid separation or dryer (crystallizer:, solid_separation:, dryer:)"
        )
    return "\n".join(lines)
