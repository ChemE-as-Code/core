"""``lca/lca.yaml`` (kind ``lca``) and ``lca/factors.yaml`` (kind ``lca_factors``).

``lca.yaml`` holds the goal and scope of the plant's LCA (ISO 14040/44): the functional unit,
the case, how the burdens are shared between co-products, the impact categories, the map from
each foreground flow (a feed, a product, an emitted component) to its background, what the
construction phase counts (take-off rows, equipment weights) and over which life, the
background (factors, or a Brightway project) and the scenarios. It references background data,
it holds none.

``factors.yaml`` is the background that needs no licensed database: characterised factors per
unit of a flow, one value per impact category, each with its ``status``, ``source``, ``year``
and ``licence``. cheme-as-code ships no factors; the project's numbers are its own.
"""

from __future__ import annotations

import ast
import datetime as _dt
import operator
import re
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, FiniteFloat, field_validator, model_validator

from chemeascode.domains.assessment.schemas import Category as TakeoffCategory
from chemeascode.domains.assessment.schemas import RateWhere
from chemeascode.domains.process.schema import UtilityKind
from chemeascode.foundation.schema_base import Origin, Provenance, Strict, unsupported_schema
from chemeascode.foundation.uncertainty import Uncertainty as Uncertainty  # the shared model
from chemeascode.foundation.units import LCI_BASE_UNITS, LCI_UNITS

SCHEMA = "cheme/lca/v1"
#: The LCI dataset (``kind: lci_dataset``) has its own version since v2 (pre-release issue 179). A
#: v1 dataset declared the LCA files' id, :data:`DATASET_SCHEMA_V1`: it is still read, with v2's
#: defaults, and ``cheme migrate`` rewrites its ``schema:`` line.
DATASET_SCHEMA = "cheme/lci_dataset/v2"
DATASET_SCHEMA_V1 = SCHEMA

#: Units a factor may be per, by quantity kind, with the factor to the inventory's unit of that
#: kind (:data:`INVENTORY_UNITS`): ``foundation.units.LCI_UNITS``, the one unit table.
FACTOR_UNITS = LCI_UNITS
#: The unit the inventory counts each quantity kind in.
INVENTORY_UNITS = LCI_BASE_UNITS
#: The quantity kinds a functional unit may be in: an amount of a material product (mass, or a
#: gas volume at its reference state), of energy (electricity, heat, a fuel by LHV), or items.
FUNCTIONAL_KINDS = ("mass", "normal-volume", "energy", "count")
#: Units a functional unit may be in, with the factor to its kind's base unit.
FUNCTIONAL_UNITS = {u: f for u, (k, f) in LCI_UNITS.items() if k in FUNCTIONAL_KINDS}
#: ``ASSUMED`` until a published dataset or a supplier declaration (EPD) backs the number;
#: ``PROXY`` a published number for a related flow (another geography, a similar material),
#: ``ESTIMATE`` one derived by the project (a calculation, an expert judgement). A proxy or an
#: estimate states its ``basis`` and ``validity``. A flow without any factor is a gap, not an
#: estimate of 0.
FactorStatus = Literal["ASSUMED", "PUBLISHED", "EPD", "PROXY", "ESTIMATE"]
#: What may be done with the results a source contributes to: ``public`` (results may be
#: published and exported, with the attribution), ``restricted`` (kept private unless a reviewed
#: publication policy of the project allows the artifact), ``local`` (never leaves the machine:
#: no snapshot, export, download or CI artifact). The policy of a result is the most restrictive
#: of its sources'.
PublicationPolicy = Literal["public", "restricted", "local"]
PUBLICATION_ORDER: tuple[str, ...] = ("public", "restricted", "local")
#: A UUID in its canonical text form (ILCD and EcoSpold2 identify datasets and flows by one).
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


#: The system model a dataset is built under (EcoSpold2 system models; the library's default
#: build is attributional cut-off, a substitution/APOS build a labelled variant). It decides what
#: a recyclable or a by-product output carries (pre-release issue 180): under ``cutoff`` and
#: ``apos`` it leaves burden-free and earns no credit; only ``substitution`` and ``consequential``
#: credit the production it avoids.
SystemModel = Literal["cutoff", "apos", "substitution", "consequential"]
#: The system models that credit avoided production (``avoided:`` exchanges).
CREDITING_MODELS: tuple[str, ...] = ("substitution", "consequential")
#: What an output that is neither a product nor an emission is (pre-release issue 180), after
#: ecoinvent's classification by economic value: ``waste`` (sent to a treatment the producer pays
#: for: its burden is in the producer's system; this includes incineration with energy recovery,
#: where only the recovered energy leaves burden-free), ``recyclable`` (material for recycling or
#: re-use with a positive market value or an accepted scrap grade: cut-off, it leaves
#: burden-free) or ``byproduct`` (a material with value: allocation, or a credit by
#: substitution).
TreatmentKind = Literal["waste", "recyclable", "byproduct"]


class Versioned(Strict):
    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")

    @model_validator(mode="after")
    def _version(self) -> Versioned:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- lca.yaml -----------------------------------------------------------------------------------


class FunctionalUnit(Strict):
    """What the results are per: an amount of one product of the flowsheet.

    A material product (counted in kg) may be per kg or t, per Nm3 or Sm3 (through its molar
    mass from the flowsheet's composition), per MJ, kWh or GJ (through its energy content,
    ``allocation.properties.<product>.energy``, e.g. the LHV) or per item (``kg_per_unit``). An
    energy product (electricity from CHP, exported steam, counted in kWh) is per kWh, MWh, MJ
    or GJ."""

    product: str = Field(description="Product id in process/flowsheet.yaml, e.g. GOXP.")
    amount: float = Field(default=1.0, gt=0)
    unit: str = Field(
        default="t", description="kg, t, g, Nm3, Sm3, kWh, MWh, MJ, GJ or ea (an item)."
    )
    kg_per_unit: FiniteFloat | None = Field(
        default=None,
        gt=0,
        description="The product's mass per unit of the functional unit where it cannot be "
        "derived (an item), or to override the derived one, with source.",
    )
    source: str = Field(default="", description="Of kg_per_unit.")

    @model_validator(mode="after")
    def _unit(self) -> FunctionalUnit:
        if self.unit not in FUNCTIONAL_UNITS:
            raise ValueError(f"functional unit {self.unit!r}: one of {', '.join(FUNCTIONAL_UNITS)}")
        return self


#: Allocation methods. All but ``substitution`` and ``none`` share the burdens in proportion to a
#: weight of each product: its mass, mass x price, mass x energy (e.g. LHV), its exergy, or given
#: shares.
AllocationMethod = Literal["mass", "economic", "energy", "exergy", "shares", "substitution", "none"]
ALLOCATION_METHODS: tuple[str, ...] = (
    "mass",
    "economic",
    "energy",
    "exergy",
    "shares",
    "substitution",
    "none",
)


class ProductProperties(Strict):
    """What allocation weighs a product by, per unit of it (per kg for a material product)."""

    price: FiniteFloat | None = Field(
        default=None, ge=0, description="Price per unit, any currency."
    )
    energy: FiniteFloat | None = Field(
        default=None, ge=0, description="Energy content per unit, kJ (e.g. lower heating value)."
    )
    exergy: FiniteFloat | None = Field(
        default=None,
        ge=0,
        description="Exergy per unit, kJ (chemical + physical, dead state 298.15 K, 101.325 "
        "kPa); plant products take it from the flowsheet (cheme process props --fill).",
    )
    source: str = Field(default="", description="Where the numbers come from.")


class StudyUncertainty(Strict):
    """Monte Carlo of the study: how often, from which seed (results are reproducible), and the
    uncertainty of every value that gives none of its own, by its origin or provenance."""

    iterations: int = Field(default=1000, ge=10, le=100_000)
    seed: int = 1
    defaults: dict[Provenance | Literal["estimated"] | Origin, Uncertainty] = Field(
        default_factory=dict,
        description="By provenance (given, calculated, estimated, assumed), e.g. {assumed: "
        "{gsd2: 1.5}, calculated: {gsd2: 1.1}}, or "
        "by origin (measured: {gsd2: 1.02}), which wins over the provenance for the values "
        "that give it.",
    )
    factors: Uncertainty | None = Field(
        default=None, description="Of every factor without its own (backend factors)."
    )


#: Compartments of an elementary flow: emissions to air, water or soil; ``resource`` a flow
#: taken from nature.
Compartment = Literal["air", "water", "soil", "resource"]
#: Sub-compartments by compartment, after EF 3.1 (pre-release issue 175): characterisation of
#: particulates, NOx, NH3 or metals differs between a ground-level and a high-stack release.
SUBCOMPARTMENTS: dict[str, tuple[str, ...]] = {
    "air": ("unspecified", "urban-close-to-ground", "non-urban-high-stack", "lower-stratosphere"),
    "water": ("unspecified", "fresh-surface", "ground", "sea"),
    "soil": ("unspecified", "agricultural", "industrial"),
    "resource": ("unspecified", "in-air", "in-water", "in-ground", "land"),
}
#: Origins of carbon-containing flows (ISO 14067, EF 3.1).
CarbonOrigin = Literal["fossil", "biogenic", "land-use-change"]
#: The reference elementary-flow lists an identity may be in: the EF 3.1 reference package
#: (primary), ecoinvent's biosphere3 (Brightway), the US Federal LCA Commons list (FEDEFL).
FlowList = Literal["ef-3.1", "biosphere3", "fedefl"]


class Elementary(Strict):
    """An elementary flow characterised directly by its component's CAS number
    (process/materials.yaml): an emission, or a resource (``compartment: resource``). With backend
    factors through the packaged method a category names (``elementary:`` of a category in
    lca/factors.yaml, e.g. ipcc2021-gwp100), with backend brightway as the biosphere flow of
    that CAS number in ``brightway.biosphere``. Its identity in the reference lists comes from
    the packaged crosswalk (``data/elementary-flows.yaml``), by CAS, compartment and origin, or
    by ``flow`` (the crosswalk id, e.g. water-river)."""

    compartment: Compartment = "air"
    subcompartment: str = Field(
        default="unspecified",
        description="air: unspecified, urban-close-to-ground, non-urban-high-stack, "
        "lower-stratosphere; water: unspecified, fresh-surface, ground, sea; soil: unspecified, "
        "agricultural, industrial; resource: unspecified, in-air, in-water, in-ground, land.",
    )
    origin: CarbonOrigin = "fossil"
    flow: str | None = Field(
        default=None,
        description="The crosswalk id when CAS and compartment do not decide (a water source: "
        "water-river, water-lake, water-sea, water-well, water-cooling).",
    )

    @model_validator(mode="after")
    def _subcompartment(self) -> Elementary:
        if self.subcompartment not in SUBCOMPARTMENTS[self.compartment]:
            raise ValueError(
                f"subcompartment {self.subcompartment!r} of {self.compartment}: one of "
                + ", ".join(SUBCOMPARTMENTS[self.compartment])
            )
        return self


#: Where a captured CO2 feedstock comes from (CCU): a fossil point source (flue gas of a
#: fossil-fired plant, the CO2 of ammonia or SMR hydrogen), a biogenic point source
#: (fermentation, biomass combustion) or direct air capture. A fossil point source is never a
#: removal: its carbon stays fossil.
Co2Source = Literal["fossil-point-source", "biogenic-point-source", "direct-air-capture"]
CO2_SOURCES: tuple[str, ...] = (
    "fossil-point-source",
    "biogenic-point-source",
    "direct-air-capture",
)


class CarbonContent(Strict):
    """The carbon an exchange carries, per kg of it: ``total`` (kg C/kg) and the
    ``biogenic_fraction`` of that carbon (non-fossil: biogenic or atmospheric). Unset: derived
    (the composition's formulas, the traced carbon of the inputs; :mod:`.carbon`)."""

    total: FiniteFloat | None = Field(
        default=None, ge=0, le=1, description="kg of carbon per kg, e.g. 0.3748 for methanol."
    )
    biogenic_fraction: FiniteFloat | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Share of the carbon that is biogenic (or atmospheric, from direct air "
        "capture); the rest is fossil. An input without it counts as fossil.",
    )
    source: str = Field(default="", description="Where the numbers come from.")


class GeologicalStorage(Strict):
    """CCS: CO2 sent to transport and geological storage (a technosphere output), with what
    makes the storage permanent."""

    permanence: str = Field(
        min_length=3,
        description="Why the storage is permanent, e.g. saline aquifer under the EU CCS "
        "Directive 2009/31/EC, monitored, with the leakage it assumes.",
    )
    reservoir: str = Field(default="", description="e.g. depleted gas field, saline aquifer.")
    source: str = ""


class FlowIdentity(Strict):
    """An elementary flow's identity in one reference list. ``uuid: null`` records a flow
    whose identifier in that list is not verified yet (a TODO, reported)."""

    list: FlowList
    uuid: str | None = Field(default=None, pattern=UUID_PATTERN)
    name: str = ""
    categories: list[str] = Field(default_factory=list, description="The list's compartments.")
    unit: str = Field(default="", description="The list's unit, e.g. m3 for water.")
    per_unit: FiniteFloat = Field(
        default=1.0, gt=0, description="The list's unit per unit of the exchange (water: 0.001)."
    )


class Allocation(Strict):
    """How the burdens of a multi-product process are shared between its products.

    The inventory itself stays unallocated (an LCI dataset); allocation is a choice of the study:

    - ``mass``, ``economic`` (mass x price), ``energy`` (mass x energy content), ``exergy``
      (each product's exergy flow), ``shares`` (given fractions): the burdens in proportion;
    - ``substitution`` (system expansion): the functional unit's product carries everything, and
      every other co-product is credited with the production it avoids (``substitution``: its
      background, e.g. the market for liquid nitrogen);
    - ``none``: the functional unit's product carries everything (a single-product process, or
      a deliberately conservative view).

    Every method whose data is complete is also computed for comparison (``compare``). Products
    of the flowsheet not listed in ``coproducts`` are not products: map them (``emission``,
    ``free``, or a background for their treatment).
    """

    method: AllocationMethod = "mass"
    coproducts: list[str] = Field(
        default_factory=list,
        description="Product ids that share the burdens; the functional unit's product is "
        "always one of them (added when missing).",
    )
    prices: dict[str, FiniteFloat] = Field(
        default_factory=dict,
        description="method=economic: price per kg of each co-product and of the functional "
        "unit's product, any one currency (or properties.<product>.price).",
    )
    properties: dict[str, ProductProperties] = Field(
        default_factory=dict,
        description="Per product: price, energy or exergy per kg (overrides what the flowsheet "
        "gives).",
    )
    shares: dict[str, FiniteFloat] = Field(
        default_factory=dict, description="method=shares: each co-product's fraction (sum 1)."
    )
    substitution: dict[str, Background] = Field(
        default_factory=dict,
        description="method=substitution: the avoided production of each co-product other than "
        "the functional unit's.",
    )
    compare: list[AllocationMethod] | None = Field(
        default=None,
        description="Methods to compare with (default: every method whose data is complete).",
    )
    source: str = Field(default="", description="Why this method, e.g. DESIGN.md D-040.")
    deviation: str = Field(
        default="",
        description="Why the method departs from the library's multi-functionality hierarchy "
        "(e.g. a sector PCR), when it does.",
    )

    @model_validator(mode="after")
    def _prices(self) -> Allocation:
        if self.method == "economic":
            missing = [
                p
                for p in self.coproducts
                if p not in self.prices
                and (p not in self.properties or self.properties[p].price is None)
            ]
            if missing:
                raise ValueError(f"economic allocation needs prices of {', '.join(missing)}")
        negative = [p for p, v in self.prices.items() if v < 0]
        if negative:
            raise ValueError(f"negative prices: {', '.join(negative)}")
        if self.shares:
            if any(v < 0 for v in self.shares.values()):
                raise ValueError("allocation shares must not be negative")
            if abs(sum(self.shares.values()) - 1.0) > 1e-6:
                raise ValueError(f"allocation shares sum to {sum(self.shares.values()):g}, not 1")
        if self.method == "shares" and not self.shares:
            raise ValueError("method shares needs shares: {product: fraction}")
        if self.method == "substitution" and not self.substitution:
            raise ValueError("method substitution needs substitution: {co-product: background}")
        for product, background in self.substitution.items():
            background._check(f"substitution {product}")
        return self

    def product_properties(self, product: str) -> ProductProperties:
        """The given properties of *product*, with a price from ``prices``."""
        given = self.properties.get(product, ProductProperties())
        if given.price is None and product in self.prices:
            return given.model_copy(update={"price": self.prices[product]})
        return given


class Activity(Strict):
    """A process of a Brightway database (e.g. an ecoinvent market activity), found by name and,
    where the name alone is ambiguous, its reference product and location."""

    database: str = Field(min_length=1, description="e.g. ecoinvent-3.10-cutoff")
    name: str = Field(min_length=1, description="e.g. market for electricity, medium voltage")
    reference_product: str | None = None
    location: str | None = Field(default=None, description="e.g. DE, RER, GLO")


class BiosphereFlow(Strict):
    """An elementary flow of a Brightway biosphere database, characterised directly by the
    method (an emission of the plant itself)."""

    database: str = Field(min_length=1, description="e.g. ecoinvent-3.10-biosphere")
    name: str = Field(min_length=1, description="e.g. Carbon dioxide, fossil")
    categories: list[str] = Field(
        default_factory=list,
        description="Compartments, e.g. [air] or [air, urban air close to ground].",
    )


class DatasetRef(Strict):
    """An LCI dataset (``kind: lci_dataset``) as the background of a flow: one unit of its
    *product*, allocated by *allocation* (default: the dataset's own default, else mass). The
    dataset's own exchanges are characterised with the study's backend, recursively."""

    path: str = Field(min_length=1, description="The dataset file, from the repository root.")
    product: str = Field(min_length=1, description="Its product, e.g. H2 or product:H2.")
    allocation: AllocationMethod | None = Field(
        default=None, description="Default: the dataset's allocation.method, else mass."
    )


class Background(Strict):
    """Where a flow's burdens come from. ``factor`` serves the factors backend, ``activity`` or
    ``biosphere`` the Brightway backend; a mapping may give both kinds, so either backend can
    run. ``dataset`` (another LCI dataset) serves both and excludes the others. ``free`` and
    ``emission`` exclude the rest."""

    factor: str | None = Field(default=None, description="Id of a factor in lca/factors.yaml.")
    activity: Activity | None = Field(default=None, description="backend brightway.")
    biosphere: BiosphereFlow | None = Field(default=None, description="backend brightway.")
    dataset: DatasetRef | None = Field(
        default=None, description="An LCI dataset of this or another study (the Atlas)."
    )
    elementary: Elementary | None = Field(
        default=None,
        description="emission:<component> only: characterised by its CAS number (a category's "
        "elementary method, or brightway.biosphere).",
    )
    source: str = Field(min_length=3, description="Why this mapping.")
    proxy: str = Field(
        default="",
        description="The background stands in for a related flow (another material, "
        "geography or technology): why, and where that holds. The results mark it PROXY.",
    )
    missing: str = Field(
        default="",
        description="No background is available (yet): why. The exchange stays in the "
        "inventory with its quantity and is a gap in every category, never 0.",
    )
    notes: str | None = None

    def _check(self, name: str, *exclusive: bool) -> None:
        if self.missing:
            exclusive = (*exclusive, True)
        if self.activity is not None and self.biosphere is not None:
            raise ValueError(f"{name}: give activity or biosphere, not both")
        direct = self.factor is not None or self.activity is not None or self.biosphere is not None
        if self.dataset is not None and direct:
            raise ValueError(f"{name}: a dataset excludes factor, activity and biosphere")
        if self.elementary is not None and (direct or self.dataset is not None):
            raise ValueError(f"{name}: elementary excludes factor, activity, biosphere, dataset")
        backed = direct or self.dataset is not None or self.elementary is not None
        if any(exclusive) and backed:
            raise ValueError(
                f"{name}: free, emission, resource and missing take no factor, activity, "
                "biosphere or dataset"
            )
        if sum(exclusive) + (1 if backed else 0) != 1:
            raise ValueError(
                f"{name}: give one of factor/activity/biosphere/dataset/elementary"
                + (", free, emission, resource or missing" if exclusive else ", or missing")
            )

    def background(self) -> Background:
        """Only the background fields (what a dataset exchange keeps)."""
        return Background(
            factor=self.factor,
            activity=self.activity,
            biosphere=self.biosphere,
            dataset=self.dataset,
            elementary=self.elementary,
            source=self.source,
            proxy=self.proxy,
            missing=self.missing,
            notes=self.notes,
        )


class Treatment(Strict):
    """What becomes of an output that is neither a product nor an emission (pre-release issue 180):
    its kind, the treatment route, and for a recyclable or a by-product the production it displaces.

    The output's own background (``factor``, ``activity``, ``dataset``: e.g. landfill of spent
    zeolite, incineration of waste mineral oil, or an Atlas utility dataset) is the treatment.
    A ``waste`` counts it under every system model. A ``recyclable`` or ``byproduct`` counts it
    only under a crediting system model (substitution, consequential); under cut-off and APOS it
    leaves burden-free (the recycler carries the treatment), except a ``hazardous`` recyclable,
    which counts its background under every system model. ``credit`` is applied only under a
    crediting system model, for every kind: it is how a substitution variant credits the heat or
    electricity an incineration (a ``waste``) displaces.

    ``recyclable`` is for material recycling and re-use only, with a positive market value or an
    accepted scrap grade. Energy recovery is a ``waste`` linked to its incineration: in the
    cut-off model the burden of the incineration stays with the waste producer. The composition
    of the waste (Doka 2003) does not change the treatment's burden here (known limitation)."""

    kind: TreatmentKind
    route: str = Field(
        min_length=3,
        description="The treatment route, e.g. landfill, incineration of waste mineral oil, "
        "re-refining, metal recovery, regeneration, wastewater treatment.",
    )
    credit: Background | None = Field(
        default=None,
        description="The background of the product it displaces, per its unit (e.g. primary "
        "steel for steel scrap, or grid electricity for the energy of an incineration); written "
        "as a negative avoided:<key> input only under a crediting system model (substitution, "
        "consequential), never in cut-off or apos.",
    )
    ratio: FiniteFloat = Field(
        default=1.0,
        gt=0,
        description="Units displaced per unit of the output (quality and losses of recycling).",
    )

    hazardous: bool = Field(
        default=False,
        description="A hazardous waste: a recyclable that is hazardous needs the recycler's "
        "treatment linked (a finding otherwise), as it rarely leaves burden-free; that "
        "background counts under every system model, cut-off included.",
    )

    @model_validator(mode="after")
    def _credit(self) -> Treatment:
        if self.credit is not None:
            self.credit._check("credit")
        return self


#: Element symbols of the never-cut metals a disposal or a cut flow may name (``metals``).
_ELEMENT = r"^[A-Z][a-z]?$"


def _symbols(elements: list[str], name: str) -> list[str]:
    """Element symbols, so that the never-cut check compares exact symbols (Pt, not pt)."""
    import re

    for element in elements:
        if not re.match(_ELEMENT, element):
            raise ValueError(f"{name}: element symbols (Pt, Ni, ...), not {element!r}")
    return elements


def _fractions(metals: dict[str, float], name: str) -> None:
    """Mass fractions of elements: each in (0, 1], summing to at most 1."""
    import re

    for element, fraction in metals.items():
        if not re.match(_ELEMENT, element):
            raise ValueError(f"{name}: metals are element symbols (Pt, Ni, ...), not {element!r}")
        if not 0 < fraction <= 1:
            raise ValueError(f"{name}: the mass fraction of {element} is in (0, 1]")
    if sum(metals.values()) > 1 + 1e-9:
        raise ValueError(f"{name}: the metals' mass fractions sum above 1")


class Disposal(Background):
    """What leaves the plant of a consumable or a construction material at the end of its use
    (pre-release issue 180), so that what goes in also comes out: a ``fraction`` of its mass to a
    treatment ``route``. The engine writes the output exchange ``disposal:<what>.<id>``.

    A ``waste`` gives its treatment background (or ``missing:``); incineration with energy
    recovery is a ``waste``. A ``recyclable`` (material recycling or re-use, with a positive
    market value or an accepted scrap grade) may give one (the recycling process, counted only
    under a crediting system model) or none: under cut-off it leaves burden-free.
    ``cutoff: <why>`` leaves the disposal out by the study's cut-off
    criteria: recorded in the dataset's ``cutoff:`` list and checked against them."""

    kind: Literal["waste", "recyclable"] = "waste"
    route: str = Field(
        min_length=3, description="e.g. landfill, incineration, re-refining, metal recovery."
    )
    fraction: FiniteFloat = Field(
        default=1.0,
        ge=0,
        le=1,
        description="Of the mass disposed. The remainder is assumed retained or used up "
        "(info cheme.lca-disposal-fraction when below 1).",
    )
    credit: Background | None = Field(
        default=None,
        description="The product it displaces, per kg (crediting system models only).",
    )
    ratio: FiniteFloat = Field(default=1.0, gt=0, description="kg displaced per kg recycled.")
    hazardous: bool = Field(default=False, description="A hazardous waste.")
    cutoff: str = Field(
        default="",
        description="Left out by the study's cut-off criteria: why. Excludes a background.",
    )

    def _disposal(self, name: str) -> None:
        backed = any(
            v is not None
            for v in (self.factor, self.activity, self.biosphere, self.dataset, self.elementary)
        )
        burden_free = self.kind == "recyclable" and not backed and not self.missing
        self._check(name, bool(self.cutoff), burden_free and not self.cutoff)
        if self.biosphere is not None or self.elementary is not None:
            raise ValueError(f"{name}: a treatment is an activity, not an elementary flow")
        self.treatment()  # its credit is checked there

    def treatment(self) -> Treatment:
        """The treatment of the output exchange it writes."""
        return Treatment(
            kind=self.kind,
            route=self.route,
            credit=self.credit,
            ratio=self.ratio,
            hazardous=self.hazardous,
        )


class FlowMap(Background):
    """The background of one foreground flow of the operation.

    ``key`` names the flow: ``feed:<id>`` or ``product:<id>`` (a terminal of the flowsheet;
    material ones counted in kg, energy ones in kWh), or ``emission:<component>`` (that
    component in every product mapped ``emission: true``, in kg). Give ``free``, ``emission``,
    or a background (``factor``, ``activity`` or ``biosphere``).
    """

    key: str = Field(pattern=r"^(feed|product|emission|resource):[A-Za-z0-9_.\-]+$")
    uncertainty: Uncertainty | None = Field(default=None, description="Of the flow's amount.")
    free: bool = Field(
        default=False,
        description="No burden: a resource taken from nature without impact (ambient air), or "
        "an output outside the system boundary.",
    )
    emission: bool = Field(
        default=False,
        description="product:<id> only: released to the environment; each of its components "
        "is an emission:<component> flow.",
    )
    resource: bool = Field(
        default=False,
        description="feed:<id> only: taken from nature (ambient air, river water); each of its "
        "components is a resource:<component> flow (an elementary resource, or free).",
    )
    treatment: Treatment | None = Field(
        default=None,
        description="product:<id> only, not a co-product or an emission: a waste, recyclable or "
        "by-product output and its route (pre-release issue 180). Its background is the treatment; "
        "a recyclable or by-product may be free (burden-free under cut-off).",
    )
    co2_source: Co2Source | None = Field(
        default=None,
        description="feed:<id> only: a captured CO2 feedstock (CCU) and where it was captured; "
        "its background is the capture, purification and compression.",
    )
    storage: GeologicalStorage | None = Field(
        default=None,
        description="product:<id> only: CO2 to transport and geological storage (CCS); its "
        "background is the transport and storage.",
    )

    @model_validator(mode="after")
    def _one(self) -> FlowMap:
        self._check(self.key, self.free, self.emission, self.resource)
        if self.treatment is not None:
            if not self.key.startswith("product:") or self.emission:
                raise ValueError(f"{self.key}: only a product that is no emission has a treatment")
            if self.treatment.kind == "waste" and self.free:
                raise ValueError(
                    f"{self.key}: a waste is not free: give its treatment's background, or "
                    "missing: (kind recyclable when it leaves burden-free)"
                )
        if self.co2_source is not None and not self.key.startswith("feed:"):
            raise ValueError(f"{self.key}: only a feed is a captured CO2 feedstock (co2_source)")
        if self.storage is not None and (not self.key.startswith("product:") or self.emission):
            raise ValueError(f"{self.key}: only a product sent to storage takes storage")
        if self.emission and not self.key.startswith("product:"):
            raise ValueError(f"{self.key}: only a product can be an emission")
        if self.resource and not self.key.startswith("feed:"):
            raise ValueError(f"{self.key}: only a feed can be taken from nature (resource)")
        if self.elementary is not None:
            kind = self.key.split(":", 1)[0]
            if kind not in ("emission", "resource"):
                raise ValueError(
                    f"{self.key}: only an emission:<component> or resource:<component> is "
                    "elementary"
                )
            if (kind == "resource") != (self.elementary.compartment == "resource"):
                raise ValueError(
                    f"{self.key}: a resource:<component> has compartment resource, an "
                    "emission:<component> air, water or soil"
                )
        return self


class Consumable(Background):
    """A supply of the operation not in the flowsheet: an adsorbent or catalyst replaced every
    few years, a lubricant, a chemical bought per year. Counted per hour of operation from
    ``per_year``, or from ``per_replacement`` every ``every_years``, plus an ``initial_charge``
    spread over the plant's life (a catalyst's first fill).

    ``disposal:`` says what leaves the plant of it (spent adsorbent to landfill, waste oil to
    incineration, spent catalyst to metal recovery): the matching output exchange, so that what
    goes in also comes out (pre-release issue 180). A catalyst names its ``metals`` (mass
    fractions)."""

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    uncertainty: Uncertainty | None = Field(default=None, description="Of the amount.")
    unit: str = Field(description="An LCI unit (foundation.units.LCI_UNITS), not tkm.")
    per_year: FiniteFloat | None = Field(default=None, ge=0)
    per_replacement: FiniteFloat | None = Field(default=None, ge=0)
    every_years: FiniteFloat | None = Field(default=None, gt=0)
    initial_charge: FiniteFloat | None = Field(
        default=None, ge=0, description="The first fill, spread over operation.life_years."
    )
    catalyst: bool = Field(default=False, description="A catalyst (never cut with its metals).")
    metals: dict[str, float] = Field(
        default_factory=dict,
        description="Element symbol -> mass fraction, e.g. {Pt: 0.003} or {Ni: 0.2}: what a "
        "spent catalyst carries to metal recovery, and what the cut-off rule never cuts.",
    )
    disposal: Disposal | None = Field(
        default=None, description="What leaves the plant of it, and to which treatment."
    )

    @model_validator(mode="after")
    def _amount(self) -> Consumable:
        self._check(self.id)
        if self.unit not in FACTOR_UNITS or FACTOR_UNITS[self.unit][0] == "transport":
            raise ValueError(f"{self.id}: unit {self.unit!r}")
        by_year = self.per_year is not None
        by_replacement = self.per_replacement is not None or self.every_years is not None
        if by_year and by_replacement or not (by_year or by_replacement or self.initial_charge):
            raise ValueError(f"{self.id}: give per_year, or per_replacement with every_years")
        if by_replacement and (self.per_replacement is None or self.every_years is None):
            raise ValueError(f"{self.id}: per_replacement needs every_years, and back")
        _fractions(self.metals, self.id)
        if self.disposal is not None:
            self.disposal._disposal(f"{self.id} disposal")
            if FACTOR_UNITS[self.unit][0] != "mass":
                raise ValueError(f"{self.id}: only a mass is disposed (unit {self.unit!r})")
        return self

    @property
    def finite(self) -> bool:
        """Replaced or charged, not used up: what is put in comes out again as spent material."""
        return self.every_years is not None or self.initial_charge is not None


class Maintenance(Strict):
    """Spare parts and repairs: a fraction of the construction materials each year, with their
    backgrounds (``maintenance:<construction id>`` exchanges)."""

    fraction_per_year: FiniteFloat = Field(ge=0, le=1, description="e.g. 0.01 (1 %/a).")
    applies_to: list[str] = Field(
        default_factory=lambda: ["*"], description="Globs on construction ids (default all)."
    )
    source: str = Field(min_length=3)


class Transport(Background):
    """Transport of material inputs, in t*km: the mass of every input exchange whose key matches
    ``applies_to`` (e.g. ``construction:*``, ``feed:CATALYST``) over ``distance_km`` (products
    and emissions are not transported here). The
    background is per t*km (factor unit tkm; Brightway: ton kilometer)."""

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    uncertainty: Uncertainty | None = Field(default=None, description="Of the amount.")
    applies_to: list[str] = Field(min_length=1, description="Globs on exchange keys.")
    distance_km: FiniteFloat = Field(gt=0)

    @model_validator(mode="after")
    def _one(self) -> Transport:
        self._check(self.id)
        return self


class EndOfLife(Background):
    """What happens to materials at their end of life: a ``fraction`` of the mass of the exchanges
    ``applies_to`` matches (construction, maintenance, consumables such as a spent adsorbent)
    leaves as a material output ``end-of-life:<id>``, per kg (pre-release issue 180).

    ``kind`` classifies it: ``waste`` (its background is the treatment, counted under every system
    model; incineration with energy recovery is a waste) or ``recyclable`` (scrap for material
    recycling or re-use: under cut-off and APOS it leaves burden-free; under substitution and
    consequential the recycling background counts). ``credit`` gives a negative ``avoided:``
    input under a crediting system model only. Without ``kind`` the entry is read as before
    (the output linked to its background), with a finding: a credit hidden in a background with
    a negative impact is not allowed in a cut-off study."""

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    uncertainty: Uncertainty | None = Field(default=None, description="Of the amount.")
    applies_to: list[str] = Field(min_length=1, description="Globs on exchange keys.")
    fraction: FiniteFloat = Field(default=1.0, ge=0, le=1)
    kind: Literal["waste", "recyclable"] | None = Field(
        default=None,
        description="waste or recyclable; unset: an entry from before pre-release issue 180.",
    )
    route: str = Field(default="", description="e.g. steel scrap to an electric arc furnace.")
    credit: Background | None = Field(
        default=None,
        description="The product it displaces, per kg (crediting system models only).",
    )
    ratio: FiniteFloat = Field(default=1.0, gt=0, description="kg displaced per kg recycled.")
    hazardous: bool = Field(default=False, description="A hazardous waste.")

    @model_validator(mode="after")
    def _one(self) -> EndOfLife:
        backed = any(
            v is not None
            for v in (self.factor, self.activity, self.biosphere, self.dataset, self.elementary)
        )
        if self.kind is None and (self.route or self.credit is not None):
            raise ValueError(f"{self.id}: route and credit need kind: waste or recyclable")
        self._check(self.id, self.kind == "recyclable" and not backed and not self.missing)
        if self.kind is not None:
            if not self.route:
                raise ValueError(f"{self.id}: kind {self.kind} names its route")
            self.treatment()
        return self

    def treatment(self) -> Treatment | None:
        """The treatment of its output exchange (None for an entry without kind)."""
        if self.kind is None:
            return None
        return Treatment(
            kind=self.kind,
            route=self.route,
            credit=self.credit,
            ratio=self.ratio,
            hazardous=self.hazardous,
        )


class CutoffEntry(Strict):
    """A flow the study leaves out by its cut-off criteria, recorded with its amount so that the
    criteria can be checked (pre-release issue 180). ISO 14044 4.2.3.3 names the types of criteria
    (mass, energy, environmental significance) but no number; the Atlas choice (process-library
    docs/system-model.md) is a flow below 1 % of the process's input mass, all cut flows
    together below 1 %, and never a precious or critical metal or a flow with a high
    characterisation factor (:mod:`.cutoff`)."""

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    direction: Literal["input", "output"] = "input"
    unit: str = Field(default="kg", description="An LCI unit; the criteria check masses.")
    per_year: FiniteFloat | None = Field(
        default=None, ge=0, description="Its amount per year of operation; unset: not known."
    )
    reason: str = Field(min_length=3, description="Why it is left out.")
    cas: str | None = Field(default=None, description="Its CAS number, if one substance.")
    catalyst: bool = False
    contains: list[str] = Field(
        default_factory=list, description="Element symbols it contains (Pt, Ni, Hg, ...)."
    )
    source: str = ""

    @field_validator("contains")
    @classmethod
    def _elements(cls, value: list[str]) -> list[str]:
        return _symbols(value, "cutoff contains")

    @model_validator(mode="after")
    def _unit(self) -> CutoffEntry:
        if self.unit not in FACTOR_UNITS or FACTOR_UNITS[self.unit][0] == "transport":
            raise ValueError(f"cutoff {self.id}: unit {self.unit!r}")
        return self


# -- emission estimates (pre-release issue 176) ----------------------------------------------------

#: The methods of ``emission_estimates:`` (pre-release issue 176): emissions a steady-state
#: flowsheet does not carry. ``combustion`` (fired heaters, boilers, gas turbines, thermal
#: oxidisers): fuel x factor per substance; ``equipment-leaks``: component count x average factor
#: per component type x the hours under pressure, less an LDAR reduction, speciated by the stream's
#: composition; ``storage-tank``: a declared loss fraction of the throughput, or a loss rate
#: calculated elsewhere (e.g. AP-42 ch. 7.1), speciated; ``flare``: the unburned slip (1 -
#: combustion efficiency) of the gas flared, speciated, and products per gas flared; ``effluent``: a
#: concentration per substance after the declared treatment x the water flow, less a removal
#: fraction; ``non-routine``: a declared fraction of other estimates or simulated emissions
#: (start-up, shutdown, upsets), kept apart (``emission:<substance>.non-routine``).
EmissionMethod = Literal[
    "combustion", "equipment-leaks", "storage-tank", "flare", "effluent", "non-routine"
]
EMISSION_METHODS: tuple[str, ...] = (
    "combustion",
    "equipment-leaks",
    "storage-tank",
    "flare",
    "effluent",
    "non-routine",
)
#: Component types of the equipment-leak method, after the US EPA protocol's categories (the
#: factors themselves are the study's, with their source).
LeakComponent = Literal[
    "valve",
    "relief-valve",
    "flange",
    "connector",
    "pump-seal",
    "compressor-seal",
    "agitator-seal",
    "open-ended-line",
    "sampling-connection",
    "other",
]
#: The service an equipment-leak estimate's components are in (the factor depends on it).
LeakService = Literal["gas", "light-liquid", "heavy-liquid"]
#: The suffix of a non-routine emission's key: ``emission:<substance>.non-routine``.
NON_ROUTINE = ".non-routine"
_SUBSTANCE = r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$"


class EmissionFactor(Strict):
    """An emission factor (or concentration) the study supplies: ``value`` in ``unit`` with its
    ``source`` (a guidebook table, AP-42 section, permit, BREF BAT-AEL, measurement). ``set``
    and ``id`` instead name an entry of a packaged factor set (``data/emission-factors/``);
    a set that holds no verified values refuses to run (no factor is ever made up)."""

    value: FiniteFloat | None = Field(default=None, ge=0)
    unit: str = Field(
        default="",
        description="<mass>/<basis>: kg, g or mg per kg, t, kWh, MJ, GJ, m3, L, Nm3 (combustion, "
        "flare, effluent), per h (a leak factor per component), or kg/h, kg/a (a storage loss "
        "rate).",
    )
    source: str = Field(default="", description="The table, section or document it is from.")
    set: str | None = Field(default=None, description="A packaged factor set's id.")
    id: str | None = Field(default=None, description="The entry of that set.")
    uncertainty: Uncertainty | None = None

    @model_validator(mode="after")
    def _given(self) -> EmissionFactor:
        if self.set is not None or self.id is not None:
            if self.set is None or self.id is None:
                raise ValueError("a factor from a packaged set names both set and id")
            if self.value is not None:
                raise ValueError("a factor from a packaged set gives no value of its own")
            return self
        if self.value is None or "/" not in self.unit or len(self.source.strip()) < 3:
            raise ValueError(
                "an emission factor gives value, unit (<mass>/<basis>) and source, or set and id"
            )
        return self


class EmissionParameter(Strict):
    """A number an estimate needs (a heating value, a density, a fraction), with its source."""

    value: FiniteFloat = Field(ge=0)
    unit: str = ""
    source: str = Field(min_length=3)


class EmissionActivity(Strict):
    """An activity per hour of operation given directly (a fuel rate from the duty, a flow not
    in the flowsheet)."""

    value: FiniteFloat = Field(ge=0)
    unit: str = Field(description="An LCI unit: kg, t, kWh, MJ, GJ, m3, L, Nm3.")
    source: str = Field(min_length=3)

    @model_validator(mode="after")
    def _unit(self) -> EmissionActivity:
        if self.unit not in LCI_UNITS:
            raise ValueError(f"activity unit {self.unit!r}: an LCI unit (kg, kWh, GJ, m3, ...)")
        return self


class EmissionEstimate(Strict):
    """One emission estimate of ``lca/lca.yaml`` (pre-release issue 176): what the flowsheet does
    not carry.

    The scope is what it covers: ``equipment`` (tag globs: the fired heater, the tanks, the
    pumps and compressors of a leak estimate) and ``stream`` (a flowsheet stream) or
    ``exchange`` (a feed or product of the dataset, e.g. feed:FUEL, product:WW). The activity is
    ``activity`` when given, else the exchange's or the stream's flow; the speciation (leaks,
    tanks, flare slip) the stream's (or exchange's) composition over ``components``. Every
    factor is the study's, with its source; the engine writes ``emission:<substance>``
    exchanges of provenance ``estimated`` with the method in ``source``."""

    id: str = Field(pattern=r"^[A-Za-z0-9_\-]+$")
    title: str = ""
    method: EmissionMethod
    equipment: list[str] = Field(
        default_factory=list, description="Tag globs of the equipment it covers, e.g. [H-101]."
    )
    stream: str | None = Field(default=None, description="A flowsheet stream id.")
    exchange: str | None = Field(
        default=None, description="A feed or product of the dataset, e.g. feed:FUEL."
    )
    activity: EmissionActivity | None = Field(
        default=None, description="The activity per hour of operation, instead of the flow."
    )
    components: list[str] = Field(
        default_factory=list,
        description="Speciation: the stream's components the total is shared among, by mass "
        "(e.g. the organics only); default every component. flare: the combustibles that slip "
        "unburned, each by its own share of the gas (required: the inerts pass through).",
    )
    factors: dict[str, EmissionFactor] = Field(
        default_factory=dict,
        description="combustion, flare: substance -> factor per activity; effluent: substance "
        "-> concentration; equipment-leaks: component type -> factor per component.",
    )
    lhv: EmissionParameter | None = Field(
        default=None,
        description="Heating value on the basis of the factors (net, LHV, unless the factor's "
        "source is per gross, HHV), MJ/kg (also GJ/t, kJ/kg, kWh/kg): converts a fuel's mass "
        "to energy.",
    )
    density: EmissionParameter | None = Field(
        default=None,
        description="kg/m3 (also g/L, kg/L, t/m3): converts a mass flow to a volume (effluent).",
    )
    efficiency: EmissionParameter | None = Field(
        default=None, description="flare: the combustion efficiency, a fraction (unburned slip)."
    )
    loss: EmissionParameter | None = Field(
        default=None, description="storage-tank: the lost fraction of the throughput."
    )
    rate: EmissionFactor | None = Field(
        default=None,
        description="storage-tank: the total loss calculated elsewhere, kg/h or kg/a (e.g. "
        "working and breathing losses after AP-42 ch. 7.1).",
    )
    removal: dict[str, EmissionParameter] = Field(
        default_factory=dict,
        description="effluent: substance -> fraction removed by the treatment after the "
        "concentration's point of measurement.",
    )
    treatment: str = Field(default="", description="effluent: the declared treatment.")
    service: LeakService | None = Field(default=None, description="equipment-leaks.")
    count_from: list[Literal["mto", "equipment"]] = Field(
        default_factory=lambda: ["mto", "equipment"],
        description="equipment-leaks: where the component counts come from: valves and flanges "
        "of estimate/mto.csv (the P&ID take-off), pump and compressor seals of the equipment "
        "list.",
    )
    where: RateWhere | None = Field(
        default=None, description="equipment-leaks: which take-off rows it counts (globs)."
    )
    counts: dict[LeakComponent, int] = Field(
        default_factory=dict,
        description="equipment-leaks: component type -> count, replacing the automatic count.",
    )
    ldar: dict[LeakComponent, EmissionParameter] = Field(
        default_factory=dict,
        description="equipment-leaks: component type -> the fraction an LDAR programme removes.",
    )
    hours_per_year: EmissionParameter | None = Field(
        default=None,
        description="equipment-leaks: hours a year under pressure; default the operating hours.",
    )
    of: list[str] = Field(
        default_factory=list,
        description="non-routine: the estimate ids or emission:<component> keys it is a share of.",
    )
    fraction: EmissionParameter | None = Field(
        default=None, description="non-routine: the share of what it is of."
    )
    cas: dict[str, str] = Field(
        default_factory=dict,
        description="Substance -> CAS number, for substances not in process/materials.yaml.",
    )
    elementary: Elementary | None = Field(
        default=None,
        description="The receiving compartment of its emissions when no flows: entry maps them "
        "(they are then characterised by CAS).",
    )
    add: bool = Field(
        default=False,
        description="A substance the flowsheet emits too is added to it (info); default it is "
        "left out (warning): a simulated component is never overwritten without a finding.",
    )
    uncertainty: Uncertainty | None = Field(
        default=None, description="Of its emissions, where a factor gives none."
    )
    source: str = Field(min_length=3, description="The method and its applicability.")

    @model_validator(mode="after")
    def _complete(self) -> EmissionEstimate:
        name, method = self.id, self.method
        if self.stream is not None and self.exchange is not None:
            raise ValueError(f"emission estimate {name}: give stream or exchange, not both")
        for key in [*self.factors, *self.removal, *self.cas]:
            if method != "equipment-leaks" and not re.match(_SUBSTANCE, key):
                raise ValueError(f"emission estimate {name}: substance {key!r}")
        flowing = self.activity is not None or self.stream or self.exchange
        if method in ("combustion", "flare", "effluent") and not flowing:
            raise ValueError(
                f"emission estimate {name}: {method} needs stream, exchange or activity"
            )
        if method in ("combustion", "effluent") and not self.factors:
            raise ValueError(f"emission estimate {name}: {method} needs factors")
        if method == "flare" and self.efficiency is None and not self.factors:
            raise ValueError(f"emission estimate {name}: flare needs efficiency or factors")
        if method == "storage-tank":
            if (self.loss is None) == (self.rate is None):
                raise ValueError(f"emission estimate {name}: storage-tank gives loss or rate")
            if self.loss is not None and not flowing:
                raise ValueError(f"emission estimate {name}: a loss fraction needs a throughput")
            if not (self.stream or self.exchange):
                raise ValueError(f"emission estimate {name}: storage-tank speciates by a stream")
        if method == "equipment-leaks":
            if not self.factors or self.service is None or not (self.stream or self.exchange):
                raise ValueError(
                    f"emission estimate {name}: equipment-leaks needs service, factors per "
                    "component type and the stream (or exchange) that speciates it"
                )
            stray = sorted(set(self.factors) - set(LeakComponent.__args__))
            if stray:
                raise ValueError(f"emission estimate {name}: component types {', '.join(stray)}")
        if method == "non-routine" and (not self.of or self.fraction is None):
            raise ValueError(f"emission estimate {name}: non-routine needs of and fraction")
        for what, value in (("efficiency", self.efficiency), ("loss", self.loss)):
            if value is not None and value.value > 1:
                raise ValueError(f"emission estimate {name}: {what} is a fraction")
        fractions = [self.fraction, *self.removal.values(), *self.ldar.values()]
        if any(p is not None and p.value > 1 for p in fractions):
            raise ValueError(f"emission estimate {name}: fractions are at most 1")
        return self


class EmissionExclusion(Strict):
    """A source of emissions the study declares negligible or out of scope, with its reason
    (e.g. leaks of inert gases, cryogenic tanks without vapour losses of a pollutant): it
    satisfies the completeness warning and is recorded among the dataset's cut-off flows."""

    id: str = Field(pattern=r"^[A-Za-z0-9_\-]+$")
    method: EmissionMethod
    equipment: list[str] = Field(
        default_factory=list, description="Tag globs; empty with no exchange: every source."
    )
    exchange: str | None = Field(default=None, description="A product, e.g. product:WW.")
    reason: str = Field(min_length=10, description="Why it is negligible or out of scope.")
    source: str = ""


class Operation(Strict):
    """How long the plant runs: spreads the construction over its output."""

    hours_per_year: float = Field(gt=0, le=8784, description="Operating hours per year.")
    life_years: float = Field(gt=0, description="Service life the construction is spread over.")
    source: str = Field(default="", description="e.g. design basis, DESIGN.md D-0xx.")


class EquipmentWhere(Strict):
    """Which equipment-list items an entry counts; every given glob must match."""

    tag: str | None = Field(default=None, description="Glob on the tag, e.g. K-*.")
    type: str | None = Field(default=None, description="Glob on the DEXPI class, e.g. *Vessel.")
    material: str | None = Field(
        default=None, description="Glob on the free-text material, e.g. '*SS*' or 'CS*'."
    )


class Construction(Background):
    """One material of the construction phase.

    ``takeoff: mto`` counts the rows of ``estimate/mto.csv`` of ``category`` that ``where``
    matches (the take-off's unit: pipe m, steel t, concrete m3, grating and insulation m2,
    fittings and valves ea; t is counted as kg). ``takeoff: equipment`` counts the empty weight
    (``dimensions.weight``, t, counted as kg) of the equipment-list items ``equipment``
    matches. A row or item is counted by the first entry that matches it, so put specific
    entries before general ones.
    """

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    cutoff: str = Field(
        default="",
        description="Left out by the study's cut-off criteria (ISO 14044 4.2.3.3): why. The rows "
        "or items it matches count nothing and are no gap; the results list it as a limitation. "
        "Excludes a background.",
    )
    title: str = ""
    uncertainty: Uncertainty | None = Field(default=None, description="Of the counted amount.")
    takeoff: Literal["mto", "equipment"]
    category: TakeoffCategory | None = Field(default=None, description="takeoff mto.")
    where: RateWhere = Field(default_factory=RateWhere, description="takeoff mto.")
    equipment: EquipmentWhere = Field(
        default_factory=EquipmentWhere, description="takeoff equipment."
    )
    disposal: Disposal | None = Field(
        default=None,
        description="What becomes of the material at the plant's end of life (and of its "
        "maintenance replacements): disposal:construction.<id> and disposal:maintenance.<id> "
        "outputs, in kg (pre-release issue 180).",
    )

    @model_validator(mode="after")
    def _one(self) -> Construction:
        self._check(self.id, bool(self.cutoff))
        if self.disposal is not None:
            if self.cutoff:
                raise ValueError(f"{self.id}: a construction entry cut off has no disposal")
            self.disposal._disposal(f"{self.id} disposal")
        if self.biosphere is not None:
            raise ValueError(f"{self.id}: a construction material is an activity, not biosphere")
        if self.takeoff == "mto" and self.category is None:
            raise ValueError(f"{self.id}: a takeoff mto entry needs its category")
        if self.takeoff == "equipment" and self.category is not None:
            raise ValueError(f"{self.id}: category is for takeoff mto")
        return self


class BrightwayCategory(Strict):
    """One impact category of the Brightway backend: a method of the project."""

    id: str = Field(min_length=1, description="e.g. climate-change")
    title: str = ""
    method: list[str] = Field(
        min_length=1,
        description="The method's name tuple, e.g. [IPCC 2021, climate change, GWP 100a, "
        "incl. H and bio CO2].",
    )


class DatabaseIdentity(Strict):
    """What a Brightway database must be, checked against its metadata (``bd.databases[name]``:
    ``provider``, ``version``, ``system_model``): a local name alone does not identify a
    database. Only the given fields are checked."""

    provider: str = Field(default="", description="e.g. ecoinvent, USLCI.")
    version: str = Field(default="", description="e.g. 3.10.")
    system_model: str = Field(default="", description="e.g. cutoff, apos, consequential.")
    publication: PublicationPolicy | None = Field(
        default=None,
        description="Of results this database contributes to (default: brightway.publication); "
        "public only for a database whose terms permit it, e.g. an open one.",
    )


class ProfileMatch(Strict):
    """Which flows a mapping profile entry serves, by what the flowsheet says they are (the
    provider-independent side): one feed or product by its key, or every feed of a utility kind
    (a product of a utility kind, e.g. exported power, is matched by its key only: it may be an
    export, not a supply)."""

    key: str | None = Field(
        default=None,
        pattern=r"^(feed|product):[A-Za-z0-9_.\-]+$",
        description="One flow, e.g. feed:POWER.",
    )
    utility: UtilityKind | None = Field(
        default=None,
        description="The feeds' utility.kind in process/flowsheet.yaml, e.g. electricity, "
        "steam, cooling_water.",
    )

    @model_validator(mode="after")
    def _one(self) -> ProfileMatch:
        if (self.key is None) == (self.utility is None):
            raise ValueError("match: give key or utility")
        return self


class ProfileEntry(Strict):
    """One mapping of a profile: the provider's activity for the flows it matches."""

    match: ProfileMatch
    activity: Activity
    source: str = Field(min_length=3, description="Why this activity (and who checked it).")
    proxy: str = Field(default="", description="It stands in for a related flow: why.")


class MappingProfile(Versioned):
    """A provider profile (``kind: lca_mapping_profile``, pre-release issue 168): how one background
    provider (an ecoinvent release and system model, an open database) names the activities for
    the flows a study takes, matched by the flowsheet's own terms (a key, a utility kind), so a
    study changes provider by selecting another profile. Names only: never a factor or a result
    of the provider, so it may be committed when the provider's terms allow its names."""

    kind: Literal["lca_mapping_profile"]
    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    provider: str = Field(min_length=1, description="e.g. ecoinvent, USLCI.")
    version: str = Field(default="", description="e.g. 3.11.")
    system_model: str = Field(default="", description="e.g. cutoff, apos.")
    entries: list[ProfileEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct(self) -> MappingProfile:
        matches = [(e.match.key, e.match.utility) for e in self.entries]
        if len(set(matches)) != len(matches):
            raise ValueError("an entry's match appears twice")
        return self


class Brightway(Strict):
    """``backend: brightway``: the Brightway project the activities and methods are in.

    The project lives outside the plant repository (``BRIGHTWAY2_DIR``); licensed databases are
    imported there by each user, never copied into the repository."""

    project: str = Field(min_length=1)
    categories: list[BrightwayCategory] = Field(min_length=1)
    mapping_profiles: list[str] = Field(
        default_factory=list,
        description="Provider profiles (kind lca_mapping_profile, paths from the repository "
        "root), first match first: they map the feeds and products that flows: leaves "
        "unmapped; an entry of flows: (also missing:) always wins.",
    )
    biosphere: str | None = Field(
        default=None,
        description="The biosphere database elementary emissions are found in by CAS number "
        "(e.g. ecoinvent-3.10-biosphere).",
    )
    expect: dict[str, DatabaseIdentity] = Field(
        default_factory=dict,
        description="Database name -> the provider, version and system model it must have; "
        "without it, the database is matched by name only (a warning).",
    )
    publication: PublicationPolicy = Field(
        default="restricted",
        description="Of results the project's databases contribute to: restricted (default: "
        "private unless the study's reviewed publication policy allows them), local, or "
        "public; per database in expect. A database without expect (matched by name only) is "
        "never public.",
    )

    @model_validator(mode="after")
    def _unique(self) -> Brightway:
        ids = [c.id for c in self.categories]
        if len(set(ids)) != len(ids):
            raise ValueError("a brightway category id appears twice")
        return self


#: How a scenario's electricity is procured. A grid average and a contractual (renewable)
#: supply are different claims: the second names its instrument.
ElectricitySupply = Literal["grid-average", "residual-mix", "contractual", "on-site"]


class Scenario(Strict):
    """A background other than the baseline: a prospective one (e.g. premise databases for 2050)
    or a sensitivity (a renewable electricity factor).

    ``factors`` replaces factor ids (factors backend), ``databases`` Brightway database names
    (the activities keep their names, as premise keeps them).
    """

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    factors: dict[str, str] = Field(default_factory=dict, description="Factor id -> factor id.")
    databases: dict[str, str] = Field(
        default_factory=dict, description="Database name -> database name."
    )
    source: str = Field(default="", description="e.g. premise, REMIND SSP2-PkBudg1150, 2050.")
    # -- a regional background scenario (docs/framework/lci-scenarios.md); all optional
    location: str = Field(
        default="",
        description="The geography this background represents (e.g. NL, DE): its contributions "
        "are checked against it instead of the study's location. Background applicability, not "
        "a plant location.",
    )
    year: int | None = Field(
        default=None, ge=1900, le=2200, description="The background's reference year."
    )
    electricity: ElectricitySupply | None = Field(
        default=None,
        description="How the electricity is procured in this scenario: grid-average, "
        "residual-mix, contractual (a renewable contract: needs source) or on-site.",
    )
    case: str | None = Field(
        default=None,
        description="A separately computed flowsheet case this scenario uses: the foreground "
        "changes with it (e.g. a hot-climate case). Unset: the study's case, foreground "
        "unchanged.",
    )
    missing: dict[str, str] = Field(
        default_factory=dict,
        description="Flow key -> why no background of this scenario's geography is available: "
        "the exchange keeps its quantity and is a gap, never 0.",
    )
    proxy: dict[str, str] = Field(
        default_factory=dict,
        description="Flow key -> why its background in this scenario stands in for another "
        "geography or technology: the results mark it PROXY.",
    )

    @model_validator(mode="after")
    def _regional(self) -> Scenario:
        both = sorted(set(self.missing) & set(self.proxy))
        if both:
            raise ValueError(f"scenario {self.id}: missing and proxy both name {', '.join(both)}")
        if self.electricity == "contractual" and not self.source:
            raise ValueError(
                f"scenario {self.id}: contractual electricity names its instrument (source:)"
            )
        return self

    @property
    def regional(self) -> bool:
        """A regional background scenario: judged against its own geography and year."""
        return bool(self.location)


class PublicationDecision(Strict):
    """A reviewed decision to publish results that draw on ``restricted`` sources (their terms
    permit it for this artifact). Without one, such results stay private; ``local`` sources are
    never published. A report existing, or a public foreground, is no such decision."""

    allow_restricted: bool = False
    review: str = Field(
        min_length=3, description="The review record that checked the sources' terms."
    )
    approved_by: str = Field(min_length=2, description="Who decided (a person, not an agent).")
    source: str = Field(default="", description="The terms that permit it.")


#: A URN as the PACT data model checks it.
_URN = re.compile(r"^[uU][rR][nN]:")


def pact_urn_ok(value: str) -> bool:
    """A ``urn:pact:`` identifier has the domain, the type and the id (PACT v2.3 section on
    product identifiers); any other URN is accepted, as the specification does."""
    head, _, rest = value.partition(":")
    namespace, _, tail = rest.partition(":")
    if namespace.lower() != "pact":
        return True
    parts = tail.split(":", 2)
    return len(parts) == 3 and all(parts)


class PactIdentity(Strict):
    """What a WBCSD PACT (Pathfinder) product footprint names that the study does not: the
    data owner and the product, as URNs. The PACT specification (v2.3) accepts any URN and
    recommends ``urn:pact:<domain-of-issuer>:<identifier-type>:<id>`` (e.g.
    ``urn:pact:company:customcode:buyer-assigned:1234``, ``urn:pact:cas.org:substance-number:
    67-56-1``); a ``urn:pact:`` value must have those three parts."""

    company_name: str = Field(min_length=1)
    company_ids: list[str] = Field(min_length=1, description="URNs of the data owner.")
    product_ids: list[str] = Field(min_length=1, description="URNs of the product.")
    product_name: str = Field(min_length=1, description="The product's name at the company.")
    product_description: str = ""
    cpc: str = Field(
        default="",
        pattern=r"^(\d{1,5})?$",
        description="UN CPC 2.1 code; default the dataset's classification.cpc.",
    )
    exempted_emissions_percent: float | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Share of the footprint left out of the study (PACT: at most 5 %): "
        "construction, plant end of life, transport of supplies and flows cut off by the "
        "criteria. Required when the study leaves any of them out; cheme cannot know the size.",
    )
    exempted_emissions_description: str = Field(
        default="",
        description="What the exempted share is and how it was estimated (mark ASSUMED).",
    )

    @model_validator(mode="after")
    def _urns(self) -> PactIdentity:
        if self.exempted_emissions_percent is not None and not self.exempted_emissions_description:
            raise ValueError("exempted_emissions_percent needs exempted_emissions_description")
        stray = [u for u in [*self.company_ids, *self.product_ids] if not _URN.match(u)]
        if stray:
            raise ValueError(f"not URNs (urn:...): {', '.join(stray)}")
        short = [u for u in [*self.company_ids, *self.product_ids] if not pact_urn_ok(u)]
        if short:
            raise ValueError(
                f"urn:pact: identifiers are urn:pact:<domain>:<type>:<id>: {', '.join(short)}"
            )
        return self


class IpccBasis(Strict):
    """The IPCC assessment report and time horizon of the GWP factors behind the climate
    category of a PCF (never guessed from a title). PACT states the report
    (``ipccCharacterizationFactorsSources``); cheme exports a 100-year GWP only."""

    report: Literal["AR5", "AR6"] = Field(description="IPCC assessment report of the GWPs.")
    gwp_horizon: Literal[20, 100] = Field(description="Time horizon of the GWPs in years.")


#: How biogenic carbon is counted (ISO 14067 6.4.9.4; TfS PCF Guideline v3 asks for -1/+1):
#: ``minus-one-plus-one`` counts the uptake as -1 kg CO2 and each biogenic release as +1;
#: ``zero-zero`` counts neither and declares the product's biogenic carbon content instead.
BiogenicMethod = Literal["minus-one-plus-one", "zero-zero"]


class CarbonAccounting(Strict):
    """``carbon_accounting:`` of ``lca.yaml``: the study's carbon accounting for a product
    carbon footprint (ISO 14067, TfS PCF Guideline v3, WBCSD PACT). Present: every material
    exchange gets its carbon content, the CO2/CO/CH4 emissions are split into fossil and
    biogenic by the carbon traced through the inputs, and results.md and results.csv report the
    PCF breakdown. Absent: the study is not a PCF and nothing changes."""

    biogenic: BiogenicMethod = Field(
        default="minus-one-plus-one",
        description="minus-one-plus-one (TfS v3) or zero-zero; both report the PCF excluding "
        "and including biogenic removals and the product's carbon content.",
    )
    ccu_rule: Literal["cut-off", "upstream"] = Field(
        default="cut-off",
        description="Captured CO2 feedstock: cut-off (it carries its capture burden; carbon "
        "from a biogenic point source or the air stays non-fossil and is a removal only through "
        "the product's biogenic carbon content) or upstream (the capture's benefit is claimed "
        "by the emitter or capturer: its carbon counts as fossil here, whatever its source).",
    )
    ccs: Literal["technosphere", "emitted"] = Field(
        default="technosphere",
        description="CO2 to geological storage: technosphere (an output to transport and "
        "storage, not an emission; stored biogenic CO2 is a removal) or emitted (counted as "
        "emitted with its origin, e.g. while permanence is not shown).",
    )
    content: dict[str, CarbonContent] = Field(
        default_factory=dict,
        description="By exchange key (feed:<id>, product:<id>): the carbon content where the "
        "flowsheet's composition does not give it, and the biogenic fraction of each feed "
        "(unset: fossil).",
    )
    trace_emissions: bool = Field(
        default=True,
        description="Split CO2, CO and CH4 emissions into fossil and biogenic by the traced "
        "carbon of the inputs; false keeps the mapped origin and reports a mismatch.",
    )
    pact: PactIdentity | None = Field(
        default=None, description="The data owner and product of a PACT export (--pact)."
    )
    ipcc: IpccBasis | None = Field(
        default=None,
        description="The IPCC report and GWP horizon of the climate category's factors; a "
        "PACT export needs it unless the category names a packaged method (elementary: "
        "ipcc2021-gwp100).",
    )
    source: str = Field(default="", description="Why these choices, e.g. DESIGN.md D-050.")

    @model_validator(mode="after")
    def _keys(self) -> CarbonAccounting:
        stray = [k for k in self.content if not k.startswith(("feed:", "product:"))]
        if stray:
            raise ValueError(f"carbon_accounting.content: feed:<id> or product:<id>, not {stray}")
        return self


class LcaFile(Versioned):
    """``lca/lca.yaml``: goal and scope of the plant's LCA and the map of its flows."""

    kind: Literal["lca"]
    goal: str = Field(default="", description="Why the LCA is made and for whom (ISO 14044).")
    functional_unit: FunctionalUnit
    location: str = Field(
        default="",
        description="Where the plant is (e.g. GB, DE, US-TX): factors of another geography are "
        "flagged and make the result screening.",
    )
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2200,
        description="The study's reference year: factors more than 10 years from it are flagged.",
    )
    technology: str = Field(
        default="", description="The technology the plant represents (lca/dataset.yaml)."
    )
    rights: str = Field(
        default="",
        description="The terms of the plant's own (foreground) data in lca/dataset.yaml, e.g. "
        "CC-BY-4.0; independent of the background's terms.",
    )
    boundary: Literal["gate-to-gate", "cradle-to-gate"] = Field(
        default="cradle-to-gate",
        description="gate-to-gate: the plant's own emissions only (map every feed free).",
    )
    case: str | None = Field(default=None, description="Flowsheet case; default its default.")
    allocation: Allocation = Field(default_factory=Allocation)
    categories: list[str] = Field(
        default_factory=list,
        description="backend factors: impact category ids of lca/factors.yaml to report (all "
        "when empty).",
    )
    flows: list[FlowMap] = Field(default_factory=list)
    operation: Operation | None = Field(
        default=None, description="Operating hours and life: required with construction."
    )
    construction: list[Construction] = Field(default_factory=list)
    consumables: list[Consumable] = Field(default_factory=list)
    maintenance: Maintenance | None = None
    transport: list[Transport] = Field(default_factory=list)
    end_of_life: list[EndOfLife] = Field(default_factory=list)
    system_model: SystemModel | None = Field(
        default=None,
        description="The study's system model (pre-release issue 180): what recyclable and "
        "by-product outputs carry and whether avoided production is credited. Unset: cutoff (the "
        "Atlas default), and the dataset records none unless dataset.system_model gives it.",
    )
    cutoff: list[CutoffEntry] = Field(
        default_factory=list,
        description="Flows left out by the cut-off criteria, with their amounts: recorded in the "
        "dataset's cutoff: list and checked (1 % of the input mass each and in sum, never-cut "
        "list).",
    )
    emission_estimates: list[EmissionEstimate] = Field(
        default_factory=list,
        description="Emissions the flowsheet does not carry (pre-release issue 176): combustion, "
        "equipment leaks, storage tanks, flares, effluent and non-routine operation, each with its "
        "method, scope, parameters and sourced factors; written as emission:<substance> "
        "exchanges of provenance estimated.",
    )
    emission_exclusions: list[EmissionExclusion] = Field(
        default_factory=list,
        description="Sources of emissions declared negligible or out of scope, with the reason "
        "(they satisfy cheme.lci-emissions-incomplete and are recorded as cut-off flows).",
    )
    backend: Literal["factors", "brightway"] = "factors"
    brightway: Brightway | None = None
    uncertainty: StudyUncertainty | None = Field(
        default=None, description="Monte Carlo: iterations, seed, defaults by provenance."
    )
    scenarios: list[Scenario] = Field(default_factory=list)
    publication: PublicationDecision | None = Field(
        default=None,
        description="A reviewed decision to publish results drawing on restricted sources.",
    )
    carbon_accounting: CarbonAccounting | None = Field(
        default=None,
        description="A product carbon footprint (ISO 14067, TfS, PACT): biogenic method, CCU "
        "rule, CCS, carbon contents.",
    )
    dataset: DatasetDocumentation | None = Field(
        default=None,
        description="The documentation of lca/dataset.yaml cheme cannot derive (uuid, version, "
        "geography, time, technology level, boundary, classification, modelling, review, "
        "parameters): copied into the dataset beside what cheme assess lca fills in.",
    )

    @model_validator(mode="after")
    def _unique(self) -> LcaFile:
        for what, ids in (
            ("flow", [f.key for f in self.flows]),
            ("construction", [c.id for c in self.construction]),
            ("consumable", [c.id for c in self.consumables]),
            ("transport", [c.id for c in self.transport]),
            ("end_of_life", [c.id for c in self.end_of_life]),
            ("cutoff", [c.id for c in self.cutoff]),
            ("scenario", [s.id for s in self.scenarios]),
            (
                "emission estimate or exclusion",
                [e.id for e in [*self.emission_estimates, *self.emission_exclusions]],
            ),
        ):
            seen: set[str] = set()
            for item in ids:
                if item in seen:
                    raise ValueError(f"{what} {item} appears twice")
                seen.add(item)
        if self.operation is None:
            needs = [
                name
                for name, given in (
                    ("construction", self.construction),
                    ("consumables", self.consumables),
                    ("maintenance", self.maintenance),
                    ("end_of_life", self.end_of_life),
                )
                if given
            ]
            if needs:
                raise ValueError(
                    f"{', '.join(needs)} {'needs' if len(needs) == 1 else 'need'} operation: "
                    "{hours_per_year, life_years}"
                )
        if self.backend == "brightway" and self.brightway is None:
            raise ValueError("backend brightway needs brightway: {project, categories}")
        declared = self.dataset.system_model if self.dataset is not None else None
        if self.system_model and declared and declared != self.system_model:
            raise ValueError(
                f"system_model {self.system_model} and dataset.system_model {declared} differ"
            )
        if "baseline" in {s.id for s in self.scenarios}:
            raise ValueError("scenario id baseline is reserved for the background as mapped")
        return self

    @property
    def model(self) -> str:
        """The system model the study is computed under: its own, the dataset's, else cutoff."""
        declared = self.dataset.system_model if self.dataset is not None else None
        return self.system_model or declared or "cutoff"


# -- factors.yaml -------------------------------------------------------------------------------


class Category(Strict):
    """One impact category: what the factors' values are in."""

    id: str = Field(min_length=1, description="e.g. climate-change")
    title: str = ""
    unit: str = Field(min_length=1, description="e.g. kg CO2-eq")
    method: str = Field(default="", description="e.g. IPCC 2021 GWP100, EF 3.1")
    elementary: str | None = Field(
        default=None,
        description="The packaged method category that characterises the plant's direct "
        "emissions in this category (e.g. ipcc2021-gwp100, see docs/framework/lca.md), or none "
        "when direct emissions do not contribute to it; unset, a direct emission is a gap here.",
    )


#: The dimensions on which two factors must agree to be compared
#: (docs/framework/lci-comparison-basis.md). ``basis``: ``direct`` (emissions at the plant only),
#: ``direct+upstream`` (plus fuel supply chain, well-to-tank), ``life-cycle`` (plus
#: infrastructure and manufacturing). ``delivery``: ``generation`` (per kWh generated, no T&D
#: losses) or ``consumer`` (at the point of use, losses and T&D included). ``gases``: ``co2`` or
#: ``co2e``. ``gwp``: the IPCC assessment report of the CO2e weights (``AR4/AR5``: a documented
#: mix, ``mixed``: no single basis). ``mix``: ``grid-average`` or ``residual-mix``.
#: ``accounting``: ``generation`` (territorial: the emissions of the geography's own
#: generation) or ``consumption`` (trade-adjusted).
ScopeBasis = Literal["direct", "direct+upstream", "life-cycle"]
ScopeDelivery = Literal["generation", "consumer"]
ScopeGases = Literal["co2", "co2e"]
ScopeGwp = Literal["AR4", "AR5", "AR6", "AR4/AR5", "mixed"]
ScopeMix = Literal["grid-average", "residual-mix"]
ScopeAccounting = Literal["generation", "consumption"]


class FactorScope(Strict):
    """What a factor measures, as data (pre-release issue 306): the structured scope the method-mix
    check and the scenario comparability verdict read instead of parsing free text. Every field is
    optional; an unset field is *not declared* (never assumed), so two factors that leave a
    dimension unset cannot be called like-for-like on it. A factor's own ``scope`` overrides its
    source's field by field."""

    basis: ScopeBasis | None = None
    delivery: ScopeDelivery | None = None
    gases: ScopeGases | None = None
    gwp: ScopeGwp | None = Field(
        default=None, description="Only meaningful for CO2e; leave unset when not stated."
    )
    mix: ScopeMix | None = None
    accounting: ScopeAccounting | None = None
    note: str = Field(default="", description="Why a field is set or unset, in a sentence.")

    def merged(self, over: FactorScope | None) -> FactorScope:
        """This scope with the fields *over* sets replacing its own."""
        if over is None:
            return self
        data = self.model_dump(exclude={"note"})
        data.update(over.model_dump(exclude={"note"}, exclude_none=True))
        return FactorScope(**data, note=over.note or self.note)

    @property
    def declared(self) -> bool:
        """Whether any dimension is set."""
        return any(v is not None for k, v in self.model_dump().items() if k != "note")


class Source(Strict):
    """One entry of the source registry: a dataset or publication factors come from, the exact
    version, and the terms its numbers and the results derived from them are used under.

    The registry records the terms; it does not interpret a licence or grant rights. Free access
    alone does not establish that results may be published or the numbers redistributed."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    title: str = Field(min_length=3)
    provider: str = Field(min_length=2, description="e.g. UK DESNZ, US EPA, JRC.")
    version: str = Field(min_length=1, description="The exact version, e.g. 2026 v1.2.")
    url: str = ""
    licence: str = Field(
        min_length=2,
        description="Licence or terms reference, e.g. OGL-3.0, CC-BY-4.0, CC0-1.0, ecoinvent EULA.",
    )
    attribution: str = Field(default="", description="The text the licence asks for.")
    publication: PublicationPolicy = Field(
        description="What may be done with results it contributes to (public, restricted, local)."
    )
    redistribution: bool = Field(
        default=False,
        description="True when its numbers may be bundled in a repository or release.",
    )
    geography: str = Field(default="", description="e.g. GB, EU27, US, GLO.")
    year: int | None = Field(default=None, ge=1900, le=2200, description="Reference year.")
    method: str = Field(
        default="",
        description="Its characterisation basis, e.g. IPCC AR5 GWP100: contributions to one "
        "category resting on different bases are flagged (method mix).",
    )
    checksum: str = Field(default="", description="e.g. sha256:<hex> of the file read.")
    notes: str = ""
    scope: FactorScope | None = Field(
        default=None,
        description="What its factors measure (basis, delivery point, gases, GWP, mix, "
        "accounting): the default of its factors' scope.",
    )


class Factor(Strict):
    """Characterised impacts of one unit of a flow, cradle to the flow."""

    id: str = Field(min_length=1)
    title: str = ""
    unit: str = Field(description="Per unit: an LCI unit, e.g. kg, t, kWh, MJ, m3, Nm3, tkm.")
    values: dict[str, FiniteFloat] = Field(
        min_length=1, description="Category id -> impact per unit."
    )
    status: FactorStatus
    source: str = Field(min_length=3, description="Dataset, publication or EPD.")
    source_id: str | None = Field(
        default=None, description="Its entry in the source registry (sources:)."
    )
    year: int = Field(ge=1900, le=2200, description="The reference year of the data.")
    data_year: int | None = Field(
        default=None,
        ge=1900,
        le=2200,
        description="The year the data describe, where it differs from or refines `year` (e.g. "
        "a factor set dated by its publication); unset: not declared. `year` keeps its meaning "
        "(pre-release issue 306).",
    )
    publication_year: int | None = Field(
        default=None,
        ge=1900,
        le=2200,
        description="The year the source published or versioned the data; unset: not declared.",
    )
    location: str = Field(default="", description="The geography it represents, e.g. GB.")
    licence: str = Field(
        default="",
        description="Terms the number is used under (e.g. CC BY 4.0, ecoinvent EULA); the "
        "registry entry's when it has a source_id.",
    )
    basis: str = Field(
        default="", description="PROXY and ESTIMATE: what the number is and how it was derived."
    )
    validity: str = Field(
        default="", description="PROXY and ESTIMATE: where it holds (and where it does not)."
    )
    uncertainty: Uncertainty | None = None
    notes: str | None = None
    scope: FactorScope | None = Field(
        default=None,
        description="What the factor measures (overrides its source's scope field by field); "
        "unset: not declared.",
    )

    @model_validator(mode="after")
    def _unit(self) -> Factor:
        if self.unit not in FACTOR_UNITS:
            raise ValueError(f"factor unit {self.unit!r}: one of {', '.join(FACTOR_UNITS)}")
        if self.status in ("PROXY", "ESTIMATE") and not (self.basis and self.validity):
            raise ValueError(f"factor {self.id}: a {self.status} states its basis and validity")
        if self.years_conflict():
            raise ValueError(
                f"factor {self.id}: data_year {self.data_year} is after publication_year "
                f"{self.publication_year}"
            )
        return self

    def years_conflict(self) -> bool:
        """Whether the declared data year lies after the declared publication year."""
        return (
            self.data_year is not None
            and self.publication_year is not None
            and self.data_year > self.publication_year
        )


class FactorFile(Versioned):
    """``lca/factors.yaml``: the project's characterised factors (no licensed database).

    ``include`` adds packaged open profiles (docs/framework/lca.md lists them; e.g.
    ``desnz-ghg-2026``): their sources, categories and factors, the factors' ids prefixed with
    the profile's (``desnz-ghg-2026:electricity-gb``)."""

    kind: Literal["lca_factors"]
    example: bool = Field(
        default=False,
        description="True marks example numbers: the results warn, and a gate requiring "
        "factors fails, until the project replaces them.",
    )
    include: list[str] = Field(
        default_factory=list, description="Packaged open profiles to add, e.g. desnz-ghg-2026."
    )
    publication: PublicationPolicy = Field(
        default="restricted",
        description="Of results drawing on a factor without a registry entry (source_id): "
        "restricted unless the project states its own numbers may be published (public).",
    )
    sources: list[Source] = Field(default_factory=list, description="The source registry.")
    categories: list[Category] = Field(default_factory=list)
    factors: list[Factor] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known(self) -> FactorFile:
        if not self.categories and not self.include:
            raise ValueError("give categories (or include a profile that has them)")
        ids = [c.id for c in self.categories]
        if len(set(ids)) != len(ids):
            raise ValueError("a category id appears twice")
        source_ids = [s.id for s in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("a source id appears twice")
        seen: set[str] = set()
        for factor in self.factors:
            if factor.id in seen:
                raise ValueError(f"factor id {factor.id} appears twice")
            seen.add(factor.id)
            unknown = sorted(set(factor.values) - set(ids))
            if unknown and not self.include:
                raise ValueError(f"factor {factor.id}: unknown categories {', '.join(unknown)}")
            # with include, the profiles' sources join later (backgrounds.resolve checks)
            stray = factor.source_id is not None and factor.source_id not in source_ids
            if stray and not self.include:
                raise ValueError(
                    f"factor {factor.id}: source_id {factor.source_id} is not in sources"
                )
        return self

    def source(self, factor: Factor) -> Source | None:
        """The registry entry of *factor* (None without a source_id)."""
        return next((s for s in self.sources if s.id == factor.source_id), None)


# -- emission factor sets (pre-release issue 176) --------------------------------------------------


class SetFactor(Strict):
    """One factor of a packaged emission factor set: read from the set's source, with the
    table or section it is in."""

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    method: EmissionMethod
    substance: str = Field(default="", description="What it is a factor of (or a leak type).")
    applies_to: str = Field(
        min_length=3, description="Fuel and technology, or component type and service."
    )
    value: FiniteFloat = Field(ge=0)
    unit: str = Field(description="<mass>/<basis>, as an emission_estimates factor.")
    table: str = Field(min_length=3, description="The table, section or page of the source.")
    uncertainty: Uncertainty | None = None


class EmissionFactorSet(Versioned):
    """A packaged emission factor set (``data/emission-factors/<id>.yaml``, kind
    ``emission_factors``): the registry entry of a guidebook or protocol (its exact version,
    licence and attribution in ``source``) and the factors read from it.

    ``status: placeholder`` is a set whose factors have not been read from the actual source
    and whose terms have not been checked: it holds no values, names what is open in ``todo``,
    and a factor that refers to it refuses to run. ``status: verified`` needs its ``source``
    with redistribution allowed, and its factors."""

    kind: Literal["emission_factors"]
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]*$")
    title: str = Field(min_length=3)
    provider: str = Field(min_length=2)
    status: Literal["placeholder", "verified"]
    todo: str = Field(default="", description="placeholder: what has to be done first.")
    licence_note: str = Field(
        default="", description="What is known of its terms, and what the owner has to check."
    )
    source: Source | None = Field(
        default=None, description="verified: its registry entry (version, licence, attribution)."
    )
    factors: list[SetFactor] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status(self) -> EmissionFactorSet:
        if self.status == "placeholder":
            if self.factors or self.source is not None:
                raise ValueError(
                    f"placeholder set {self.id}: no factors and no source until verified"
                )
            if len(self.todo.strip()) < 10:
                raise ValueError(f"placeholder set {self.id}: say what is open in todo")
            return self
        if self.source is None or not self.source.redistribution or not self.factors:
            raise ValueError(
                f"verified set {self.id}: needs its source (redistribution: true) and factors"
            )
        ids = [f.id for f in self.factors]
        if len(set(ids)) != len(ids):
            raise ValueError(f"set {self.id}: a factor id appears twice")
        return self

    def factor(self, name: str) -> SetFactor | None:
        return next((f for f in self.factors if f.id == name), None)


# -- lci datasets -------------------------------------------------------------------------------

#: ``foreground``: the process's own exchanges (inputs, products, its emissions), each input
#: still to be linked to a background; ``linked``: a cradle-to-gate dataset whose inputs are
#: already accounted for (e.g. an aggregated database dataset). The two must not be mixed up: a
#: foreground inventory is not a footprint.
DatasetScope = Literal["foreground", "linked"]


#: The technology level of EcoSpold2 (``technologyLevel``): relative to the technologies on the
#: market of the dataset's geography and time.
TechnologyLevel = Literal["undefined", "new", "modern", "current", "old", "outdated"]
#: Review types: ``none`` (unreviewed, stated), ``internal``, ``independent-external`` (one
#: reviewer outside the work) or ``panel`` (ISO 14071).
ReviewType = Literal["none", "internal", "independent-external", "panel"]
Inclusion = Literal["included", "excluded"]


class DatasetGeography(Strict):
    """What the dataset's geography code (``location``) stands for. The facility's place and
    where the dataset may be applied are kept apart from the code it represents."""

    description: str = Field(
        default="",
        description="Representativeness: how the data represent the location (ILCD "
        "geography/locationOfOperationSupplyOrProduction/descriptionOfRestrictions).",
    )
    site: str = Field(
        default="", description="The facility's assumed place, e.g. coastal industrial site."
    )
    applicable: list[str] = Field(
        default_factory=list,
        description="Geography codes the dataset may be applied to beyond its own "
        "(pre-release issue 172).",
    )


class DatasetTime(Strict):
    """The time the data represent; ``year`` of the dataset is the data's reference year and
    ``valid_until`` the last year it may be used."""

    start: int | None = Field(default=None, ge=1900, le=2200, description="First valid year.")
    description: str = ""


class SupersededBy(Strict):
    """The dataset (and its version) that replaces this one."""

    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class SystemBoundary(Strict):
    """The system boundary as data (ISO 14044 4.2.3.3): the steps included and excluded, the
    cut-off criteria, and whether infrastructure, catalysts and non-routine operation count."""

    included: list[str] = Field(default_factory=list, description="Process steps included.")
    excluded: list[str] = Field(default_factory=list, description="Steps left out, and why.")
    cutoff: str = Field(default="", description="The cut-off criteria applied.")
    infrastructure: Inclusion | None = None
    catalysts: Inclusion | None = None
    non_routine: Inclusion | None = Field(default=None, description="Start-up, shut-down, upsets.")


class ProductionVolume(Strict):
    """The annual output of the represented technology in its geography (market weighting)."""

    amount: FiniteFloat = Field(gt=0)
    unit: str = Field(min_length=1, description="Per year, e.g. kg/a.")
    source: str = ""


class Classification(Strict):
    """ISIC Rev.4 (the activity) and CPC Ver. 2.1 (the reference product), as ecoinvent and the
    UN statistics classify them."""

    isic: str = Field(default="", pattern=r"^(\d{2,4})?$", description="e.g. 2011.")
    cpc: str = Field(default="", pattern=r"^(\d{1,5})?$", description="A CPC 2.1 code.")


class Modelling(Strict):
    """The LCI method of the dataset (ILCD modellingAndValidation/LCIMethodAndAllocation)."""

    principle: Literal["attributional", "consequential"] | None = None
    multifunctionality: str = Field(
        default="", description="How multi-output is handled (filled from allocation)."
    )
    sampling: str = Field(default="", description="Sampling and representativeness of the data.")


def _reviews(value: object) -> object:
    """``review:`` as a list: one record, or ``unreviewed`` (``[{type: none}]``), is accepted."""
    if value in ("unreviewed", "none"):
        return [{"type": "none"}]
    return [value] if isinstance(value, dict) else value


class Review(Strict):
    """One review of the dataset; ``type: none`` states that it is unreviewed."""

    type: ReviewType
    reviewer: str = ""
    scope: str = Field(default="", description="What was reviewed, e.g. inventory, method.")
    date: _dt.date | None = None
    report: str = Field(default="", description="The review record, e.g. reviews/<file>.md.")

    @model_validator(mode="after")
    def _who(self) -> Review:
        if self.type != "none" and not self.reviewer:
            raise ValueError(f"a {self.type} review names its reviewer")
        return self


class Parameter(Strict):
    """A named parameter exchanges' ``formula`` may use (EcoSpold2 mathematical relations)."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: FiniteFloat
    unit: str = ""
    description: str = ""
    source: str = ""


class DatasetDocumentation(Strict):
    """What a professional LCI database documents of each dataset beyond its exchanges, mapped to
    ILCD (EF 3.1) and EcoSpold2 in docs/framework/lca.md. Every field is optional in the schema;
    the gate ``lci-documented`` requires the publication minimum."""

    uuid: str | None = Field(
        default=None, pattern=UUID_PATTERN, description="Stable across versions."
    )
    version: str | None = Field(
        default=None, pattern=r"^\d+\.\d+\.\d+$", description="major.minor.patch."
    )
    parent: str | None = Field(
        default=None,
        pattern=UUID_PATTERN,
        description="The uuid of the dataset this one is a (regional) variant of.",
    )
    methodology_version: str | None = Field(
        default=None,
        description="The version of the library methodology the dataset was built under.",
    )
    superseded_by: SupersededBy | None = None
    geography: DatasetGeography | None = None
    time: DatasetTime | None = None
    valid_until: int | None = Field(
        default=None, ge=1900, le=2200, description="Last year of use (ILCD dataValidUntil)."
    )
    system_model: SystemModel | None = None
    technology_level: TechnologyLevel | None = None
    system_boundary: SystemBoundary | None = None
    production_volume: ProductionVolume | None = None
    classification: Classification | None = None
    modelling: Modelling | None = None
    review: Annotated[list[Review], BeforeValidator(_reviews)] = Field(
        default_factory=list,
        description="Review records; [] or 'unreviewed' when none was made (unreviewed is "
        "stated with type: none).",
    )
    parameters: list[Parameter] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid(self) -> DatasetDocumentation:
        start = self.time.start if self.time else None
        if start is not None and self.valid_until is not None and self.valid_until < start:
            raise ValueError(f"valid_until {self.valid_until} is before time.start {start}")
        return self

    data_generator: str = Field(
        default="", description="Who modelled the data (person or organisation)."
    )
    entry_by: str = Field(default="", description="Who entered the dataset.")


_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def evaluate(formula: str, parameters: dict[str, float]) -> float:
    """The value of the arithmetic *formula* (+ - * / ** and parentheses on numbers and the
    names of *parameters*). Raises ValueError for anything else."""

    def value(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in parameters:
                raise ValueError(f"unknown parameter {node.id}")
            return parameters[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](value(node.left), value(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](value(node.operand))
        raise ValueError(f"not arithmetic: {ast.dump(node)[:40]}")

    try:
        return value(ast.parse(formula, mode="eval").body)
    except (SyntaxError, ZeroDivisionError, OverflowError) as failure:
        raise ValueError(f"formula {formula!r}: {failure}") from failure


#: What an energy exchange carries (pre-release issue 177): its burden and its background depend on
#: it.
CarrierKind = Literal["electricity", "heat", "steam", "fuel", "cold"]


class Carrier(Strict):
    """The energy carrier of an exchange and its quality: the temperature of heat or cold, the
    pressure (and level) of steam, the lower heating value of a fuel."""

    kind: CarrierKind
    temperature: FiniteFloat | None = Field(
        default=None, description="°C: heat or steam supplied, cold delivered."
    )
    pressure: FiniteFloat | None = Field(default=None, gt=0, description="bar(a): steam.")
    level: str = Field(
        default="", description="e.g. LP, MP, HP steam; a named heat or cooling level."
    )
    lhv: FiniteFloat | None = Field(default=None, gt=0, description="MJ/kg: a fuel.")
    composition: str = Field(default="", description="A fuel's stated composition.")
    source: str = ""


class ProductState(Strict):
    """A product's state, part of its identity: GOX at 30 bar(g) and LOX are distinct reference
    products. Exporters write it into the reference product's name or properties."""

    phase: Literal["gas", "liquid", "solid", "two-phase", "supercritical"] | None = None
    pressure: FiniteFloat | None = Field(default=None, gt=0, description="bar(a).")
    temperature: FiniteFloat | None = Field(default=None, description="°C.")
    purity: FiniteFloat | None = Field(
        default=None, gt=0, le=1, description="Fraction of the main component."
    )
    basis: Literal["mole", "mass"] | None = Field(default=None, description="Of the purity.")
    component: str = Field(default="", description="The main component, e.g. O2.")
    grade: str = Field(default="", description="A commercial grade, e.g. 99.5 % O2.")


class Pedigree(Strict):
    """An exchange's data quality on the ecoinvent pedigree matrix (Weidema et al. 2013): five
    scores, 1 (best) to 5, for reliability, completeness, temporal, geographical and further
    technological correlation, relative to the dataset's declared scope. Given by the default
    rule (``rule``, :mod:`.quality`) or by hand with its ``reason``."""

    scores: list[int] = Field(
        min_length=5,
        max_length=5,
        description="[reliability, completeness, temporal, geographical, technological].",
    )
    rule: str = Field(default="", description="The default rule that gave them.")
    reason: str = Field(default="", description="Why they were set by hand.")

    @model_validator(mode="after")
    def _scored(self) -> Pedigree:
        if not all(1 <= s <= 5 for s in self.scores):
            raise ValueError("pedigree scores are 1 to 5")
        if not (self.rule or self.reason):
            raise ValueError("a pedigree set by hand records its reason")
        return self


#: How far a composition's mass fractions may sum above 1 (rounding of written fractions).
COMPOSITION_ROUNDING = 1e-6
#: The key of a composition's `elements` for the mass of the residue (ash), in no element.
ASH = "ash"


class Composition(Strict):
    """What a material exchange is made of, by mass: the input of the dataset's mass and
    element balances (pre-release issue 174, :mod:`.balance`). Either ``fractions`` (component ->
    mass fraction; a component is read as a molecular formula unless ``formulas`` gives its
    formula) or ``elements`` (element symbol -> mass fraction, e.g. a fuel's ultimate
    analysis). Filled from the stream table for a flowsheet-derived dataset; a composition
    whose fractions sum below 1 is incomplete, and the element balance then names it."""

    fractions: dict[str, FiniteFloat] = Field(
        default_factory=dict, description="Component -> mass fraction, e.g. {CO2: 1.0}."
    )
    formulas: dict[str, str] = Field(
        default_factory=dict,
        description="Component -> molecular formula, where the component's name is no formula "
        "(e.g. {MEOH: CH4O}).",
    )
    elements: dict[str, FiniteFloat] = Field(
        default_factory=dict,
        description="Element symbol -> mass fraction (ultimate analysis); `ash` is the mass "
        "of the residue, counted in the mass balance and in no element.",
    )
    source: str = Field(default="", description="Where it comes from, e.g. stream S3.")

    @model_validator(mode="after")
    def _one(self) -> Composition:
        import re

        if bool(self.fractions) == bool(self.elements):
            raise ValueError("a composition gives fractions or elements (one of them)")
        given = self.fractions or self.elements
        for name, fraction in given.items():
            if not 0 <= fraction <= 1:
                raise ValueError(f"composition: the mass fraction of {name} is in [0, 1]")
        if self.elements and not all(re.match(_ELEMENT, e) or e == ASH for e in self.elements):
            raise ValueError("composition: elements are element symbols (C, H, O, ...) or ash")
        if sum(given.values()) > 1 + COMPOSITION_ROUNDING:
            raise ValueError("composition: the mass fractions sum above 1")
        stray = sorted(set(self.formulas) - set(self.fractions))
        if stray:
            raise ValueError(f"composition: formulas of components not in fractions: {stray}")
        return self


def _identities(value: object) -> object:
    return [value] if isinstance(value, dict) else value


#: Where an exchange's amount comes from: the provenance classes of the flowsheet
#: (``given``, ``calculated``, ``assumed``) and ``estimated``, an emission computed from
#: activity data and sourced emission factors (``emission_estimates:``, pre-release issue 176). In a
#: row made of several values the weakest counts: given, calculated, estimated, assumed.
ExchangeProvenance = Literal["given", "calculated", "estimated", "assumed"]
EXCHANGE_PROVENANCE: tuple[str, ...] = ("given", "calculated", "estimated", "assumed")

#: The units a resource exchange may be in (volume, land occupation and transformation, mass,
#: energy).
RESOURCE_UNITS = ("m3", "m2*a", "m2", "kg", "kWh")


class DatasetExchange(Strict):
    """One exchange of an LCI dataset, in the dataset's basis (e.g. per hour of operation)."""

    key: str = Field(
        pattern=r"^[a-z][a-z-]*:[A-Za-z0-9_.\-]+$",
        description="feed:<id>, product:<id>, emission:<component>, construction:<id>, ...",
    )
    title: str = ""
    type: Literal["product", "input", "output", "emission", "resource"] = Field(
        description="product: a (co-)product the burdens are allocated to; input: from the "
        "technosphere; output: a waste or other output; emission: to the environment; "
        "resource: an elementary flow from nature (m3, m2*a, m2, kg, MJ)."
    )
    phase: str = Field(default="operation", description="operation, construction, ...")
    amount: FiniteFloat
    unit: str = Field(
        description="The inventory unit of its kind: kg, kWh, m, m2, m2*a, m3, Nm3 (gas at "
        "0 °C, 1.01325 bar), ea, ea*h, tkm or kBq."
    )
    provenance: ExchangeProvenance = Field(
        default="assumed",
        description="given, calculated, estimated (an emission-factor estimate of "
        "emission_estimates:, pre-release issue 176) or assumed.",
    )
    origin: Origin | None = Field(
        default=None, description="The origin every value it is derived from gives, if one."
    )
    properties: ProductProperties | None = Field(
        default=None, description="Products: what allocation weighs them by."
    )
    link: Background | None = Field(
        default=None, description="Its background; none: free, or not linked yet."
    )
    free: bool = Field(default=False, description="Carries no burden (ambient air, ...).")
    cas: str | None = Field(
        default=None, description="An emission's or resource's CAS number (an attribute)."
    )
    flow: Annotated[list[FlowIdentity], BeforeValidator(_identities)] = Field(
        default_factory=list,
        description="Emissions and resources: the flow's identity in reference lists, the "
        "primary list (EF 3.1) first, e.g. [{list: ef-3.1, uuid: ...}, {list: biosphere3, "
        "uuid: ..., name: ..., categories: [...]}]; one mapping is read as a list.",
    )
    uncertainty: Uncertainty | None = None
    streams: list[str] = Field(
        default_factory=list, description="What it is derived from (streams, take-off rows)."
    )
    source: str = ""
    source_id: str | None = Field(
        default=None,
        description="The dataset's sources: entry the amount comes from, when it is externally "
        "supplied data (its terms stay with it); none: generated or sourced by the project.",
    )
    pedigree: Pedigree | None = Field(
        default=None,
        description="Its data quality (ecoinvent pedigree); unset: the default rule's, from "
        "its provenance and origin (cheme assess lca writes it).",
    )
    basic_uncertainty: FiniteFloat | None = Field(
        default=None, ge=1, description="Basic gsd2 under the pedigree, by exchange type."
    )
    carrier: Carrier | None = Field(
        default=None, description="An energy exchange's carrier and quality (kWh exchanges)."
    )
    state: ProductState | None = Field(
        default=None, description="A product's phase, pressure, temperature and purity."
    )
    carbon: CarbonContent | None = Field(
        default=None,
        description="Material exchanges (kg): the carbon it carries per kg and its biogenic "
        "fraction (products: always reported in a PCF).",
    )
    co2_source: Co2Source | None = Field(
        default=None, description="An input of captured CO2 (CCU): where it was captured."
    )
    storage: GeologicalStorage | None = Field(
        default=None, description="An output of CO2 to transport and geological storage (CCS)."
    )
    formula: str | None = Field(
        default=None,
        description="How the amount follows from the dataset's parameters, e.g. "
        "'capacity * power_per_t' (+ - * / ** and parentheses); it must give the amount.",
    )
    treatment: Treatment | None = Field(
        default=None,
        description="An output that is neither product nor emission: waste, recyclable or "
        "by-product, its route and the product it displaces (pre-release issue 180). The exchange "
        "is linked as the dataset's system_model decides: a recyclable or by-product is free "
        "under cutoff and apos.",
    )
    metals: dict[str, float] = Field(
        default_factory=dict,
        description="Element symbol -> mass fraction (a catalyst and its spent output).",
    )
    composition: Composition | None = Field(
        default=None,
        description="Material exchanges (kg, Nm3): what it is made of by mass, for the mass "
        "and element balances (pre-release issue 174); filled from the stream table for a "
        "flowsheet-derived dataset.",
    )
    balance_exclusion: str = Field(
        default="",
        description="Why it is left out of the mass and element balances, e.g. a catalyst "
        "charge counted over its life (stated, never silent; pre-release issue 174).",
    )

    @model_validator(mode="after")
    def _link(self) -> DatasetExchange:
        if self.treatment is not None and self.type != "output":
            raise ValueError(f"{self.key}: only an output has a treatment")
        if self.key.startswith("avoided:") and (self.type != "input" or self.amount > 0):
            raise ValueError(f"{self.key}: an avoided production is an input of negative amount")
        _fractions(self.metals, self.key)
        if self.free and self.link is not None:
            raise ValueError(f"{self.key}: free takes no link")
        if self.type == "product" and (self.link is not None or self.free):
            raise ValueError(f"{self.key}: a product has no background")
        if self.type == "product" and self.amount < 0:
            raise ValueError(f"{self.key}: a product's amount is not negative")
        if self.link is not None:
            self.link._check(self.key)
        if self.flow and self.type not in ("emission", "resource"):
            raise ValueError(f"{self.key}: only an emission or a resource has a flow identity")
        if self.unit not in INVENTORY_UNITS.values():
            raise ValueError(
                f"{self.key}: unit {self.unit!r}: one of {', '.join(INVENTORY_UNITS.values())}"
            )
        if self.carrier is not None and LCI_UNITS[self.unit][0] not in (
            "energy",
            "mass",
            "normal-volume",
        ):
            raise ValueError(f"{self.key}: a carrier is for energy (kWh) or a fuel by mass or Nm3")
        if self.type == "resource" and self.unit not in RESOURCE_UNITS:
            raise ValueError(f"{self.key}: a resource is in {', '.join(RESOURCE_UNITS)}")
        if (self.carbon or self.co2_source or self.storage) and self.unit != "kg":
            raise ValueError(f"{self.key}: carbon, co2_source and storage are for kg exchanges")
        if self.composition is not None and self.unit not in ("kg", "Nm3"):
            raise ValueError(f"{self.key}: a composition is for material exchanges (kg, Nm3)")
        if self.co2_source is not None and self.type != "input":
            raise ValueError(f"{self.key}: co2_source is for an input of captured CO2")
        if self.storage is not None and self.type != "output":
            raise ValueError(f"{self.key}: storage is for an output to geological storage")
        fraction = self.carbon.biogenic_fraction if self.carbon else None
        if self.co2_source == "fossil-point-source" and fraction:
            raise ValueError(
                f"{self.key}: CO2 from a fossil point source is fossil carbon (never a removal); "
                "its biogenic_fraction is 0"
            )
        return self


class CutoffFlow(Strict):
    """A flow left out by the cut-off criteria, recorded in the dataset (pre-release issue 180) so
    that the criteria can be checked where it is built and where it is used (:mod:`.cutoff`): its
    amount in the dataset's basis, why, and what the never-cut rule looks at."""

    key: str = Field(pattern=r"^[a-z][a-z-]*:[A-Za-z0-9_.\-]+$")
    title: str = ""
    direction: Literal["input", "output"] = "input"
    amount: FiniteFloat | None = Field(default=None, ge=0, description="None: not known.")
    unit: str = Field(default="kg", description="An inventory unit.")
    reason: str = Field(min_length=3)
    cas: str | None = None
    catalyst: bool = False
    contains: list[str] = Field(default_factory=list, description="Element symbols.")
    source: str = ""

    @field_validator("contains")
    @classmethod
    def _elements(cls, value: list[str]) -> list[str]:
        return _symbols(value, "cutoff contains")

    @model_validator(mode="after")
    def _unit(self) -> CutoffFlow:
        if self.unit not in INVENTORY_UNITS.values():
            raise ValueError(f"cutoff {self.key}: unit {self.unit!r}")
        return self


class DatasetProvenance(Strict):
    """Where a dataset comes from: the generator and the files it was derived from."""

    generator: str = Field(default="", description="e.g. cheme 0.7 assess lca.")
    plant: str = Field(default="", description="The plant (plant.yaml name).")
    case: str = ""
    commit: str | None = None
    files: dict[str, str] = Field(default_factory=dict, description="Path -> sha256 or blob.")
    notes: str = ""


#: The calculation maturity levels of ``cheme maturity`` (docs/framework/maturity.md), lowest
#: first: a generated dataset's ``maturity_cap`` is one of them.
MaturityLevel = Literal["sourced", "balanced", "predictive", "engineering"]
MATURITY_LEVELS: tuple[str, ...] = ("sourced", "balanced", "predictive", "engineering")
#: What each tier may claim at most (pre-release issue 182): a dataset estimated without a flowsheet
#: is never "balanced" (that level needs a balanced conceptual PFD, the flowsheet path of Tier 2).
TIER_MATURITY_CAP: dict[int, str] = {0: "sourced", 1: "sourced"}


class ElementBalanceRecord(Strict):
    """The element balance of a generated dataset as it was written: kg of each element in
    (inputs, resources) and out (products, outputs, emissions) per the dataset's basis."""

    closed: bool
    tolerance: FiniteFloat = Field(gt=0, description="Relative, of the larger side.")
    elements: dict[str, list[FiniteFloat]] = Field(
        default_factory=dict, description="Element -> [kg in, kg out]."
    )
    outside: list[str] = Field(
        default_factory=list,
        description="Exchanges outside the balance (energy, or no formula), by key.",
    )


class Generation(Strict):
    """How a dataset was generated (pre-release issue 182): its tier, the method, the versioned
    defaults it used and the caps the tier sets.

    Tier 0 is stoichiometric (reactions, a yield and defaults), Tier 1 sourced conceptual
    (yields, utilities and emissions taken from open literature, patents or BREFs), Tier 2 and
    up the flowsheet and simulation path. A dataset without ``generation`` is derived from a
    flowsheet (``cheme assess lca``) or written by hand."""

    tier: int = Field(ge=0, le=3, description="0 stoichiometric, 1 sourced conceptual, 2+.")
    method: str = Field(min_length=3, description="e.g. stoichiometric (Hischier et al. 2005).")
    defaults: str = Field(
        default="", description="The defaults file and its version, e.g. cheme tier-defaults 1.0.0."
    )
    defaults_used: list[str] = Field(
        default_factory=list, description="The ids of the default rules the exchanges took."
    )
    spec: str = Field(default="", description="The estimate it was generated from (its path).")
    maturity_cap: MaturityLevel | None = Field(
        default=None, description="The highest calculation maturity the dataset supports."
    )
    pedigree_floor: list[int] | None = Field(
        default=None,
        min_length=5,
        max_length=5,
        description="The best pedigree scores the tier allows on any exchange: [reliability, "
        "completeness, temporal, geographical, technological].",
    )
    dqr_floor: FiniteFloat | None = Field(
        default=None,
        ge=1,
        le=5,
        description="The best (lowest) TfS DQR the tier allows: the mean of the floor's "
        "temporal, geographical and technological scores.",
    )
    components: dict[str, str] = Field(
        default_factory=dict, description="Exchange key -> the component id it is an amount of."
    )
    formulas: dict[str, str] = Field(
        default_factory=dict,
        description="Exchange key -> the formula of its component: the element balance's input.",
    )
    balance: ElementBalanceRecord | None = None

    @model_validator(mode="after")
    def _capped(self) -> Generation:
        cap = TIER_MATURITY_CAP.get(self.tier)
        if cap is None:
            return self
        claimed = self.maturity_cap
        if claimed is not None and MATURITY_LEVELS.index(claimed) > MATURITY_LEVELS.index(cap):
            raise ValueError(
                f"a Tier {self.tier} dataset supports calculation maturity {cap!r} at most, "
                f"not {claimed!r} "
                "(balanced and above need the flowsheet path)"
            )
        if self.balance is None:
            raise ValueError(f"a Tier {self.tier} dataset records its element balance")
        return self


class LciDataset(DatasetDocumentation):
    """An unallocated life cycle inventory dataset (``kind: lci_dataset``): a reusable process.

    Derived from a plant (``cheme assess lca --write`` writes ``lca/dataset.yaml``) or
    written by hand, and referenced by other studies as a background (``dataset:``). It keeps
    every product unallocated; allocation is the study's choice (``allocation``: the
    dataset's default).

    ``schema: cheme/lci_dataset/v2``. A v1 dataset (``schema: cheme/lca/v1``) loads with the
    defaults of every field v2 added; :func:`.documentation.findings` names what it lacks."""

    schema_: str = Field(
        alias="schema",
        description=f"{DATASET_SCHEMA} ({DATASET_SCHEMA_V1}: a v1 dataset, read with defaults).",
    )
    kind: Literal["lci_dataset"]
    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    description: str = ""
    scope: DatasetScope = "foreground"
    basis: str = Field(default="1 h of operation", description="What the amounts are per.")
    location: str = ""
    year: int | None = Field(default=None, ge=1900, le=2200)
    boundary: str = Field(
        default="", description="What the process includes, e.g. gate-to-gate, the ASU plant."
    )
    technology: str = Field(default="", description="The technology it represents.")
    rights: str = Field(
        default="",
        description="The terms of its own data, e.g. CC-BY-4.0 (independently generated); "
        "exchanges from external sources keep theirs (source_id).",
    )
    sources: list[Source] = Field(
        default_factory=list, description="Registry of the externally supplied amounts."
    )
    exchanges: list[DatasetExchange] = Field(min_length=1)
    cutoff: list[CutoffFlow] = Field(
        default_factory=list,
        description="Flows left out by the cut-off criteria, with amount and reason "
        "(pre-release issue 180).",
    )
    allocation: Allocation | None = Field(
        default=None, description="The default allocation when a study names none."
    )
    provenance: DatasetProvenance = Field(default_factory=DatasetProvenance)
    generation: Generation | None = Field(
        default=None,
        description="How it was generated (tier, method, defaults used): set by cheme assess "
        "lci-estimate; none for a dataset from a flowsheet or written by hand.",
    )

    @model_validator(mode="after")
    def _keys(self) -> LciDataset:
        if self.schema_ not in (DATASET_SCHEMA, DATASET_SCHEMA_V1):
            raise ValueError(unsupported_schema(self.schema_, DATASET_SCHEMA))
        keys = [e.key for e in self.exchanges]
        doubled = sorted({k for k in keys if keys.count(k) > 1})
        if doubled:
            raise ValueError(f"exchanges appear twice: {', '.join(doubled)}")
        if not any(e.type == "product" for e in self.exchanges):
            raise ValueError("a dataset needs at least one product")
        known = {s.id for s in self.sources}
        stray = sorted({e.source_id for e in self.exchanges if e.source_id} - known)
        if stray:
            raise ValueError(f"exchanges name sources not in sources: {', '.join(stray)}")
        credited = [e.key for e in self.exchanges if e.key.startswith("avoided:")]
        if credited and self.system_model not in CREDITING_MODELS:
            raise ValueError(
                f"avoided-burden credits ({', '.join(credited)}) in a dataset of system model "
                f"{self.system_model or 'unset (cutoff)'}: only substitution and consequential "
                "credit avoided production"
            )
        cut = [c.key for c in self.cutoff]
        if len(set(cut)) != len(cut):
            raise ValueError("a cut-off flow appears twice")
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("a parameter name appears twice")
        values = {p.name: p.value for p in self.parameters}
        for exchange in self.exchanges:
            if exchange.formula is None:
                continue
            try:
                result = evaluate(exchange.formula, values)
            except ValueError as failure:
                raise ValueError(f"{exchange.key}: {failure}") from failure
            if abs(result - exchange.amount) > 1e-9 * max(1.0, abs(exchange.amount)):
                raise ValueError(
                    f"{exchange.key}: formula {exchange.formula} gives {result:g}, the amount "
                    f"is {exchange.amount:g}"
                )
        return self

    @property
    def version_of_schema(self) -> str:
        """``v2``, or ``v1`` for a dataset read under the v1 id."""
        return "v1" if self.schema_ == DATASET_SCHEMA_V1 else "v2"

    def products(self) -> list[DatasetExchange]:
        return [e for e in self.exchanges if e.type == "product"]

    def product(self, name: str) -> DatasetExchange | None:
        key = name if ":" in name else f"product:{name}"
        return next((e for e in self.products() if e.key == key), None)


# -- lca/estimate.yaml (kind lci_estimate) -------------------------------------------------------

#: The schema of an LCI estimate (pre-release issue 182): the input of ``cheme assess
#: lci-estimate``.
ESTIMATE_SCHEMA = "cheme/lci_estimate/v1"
#: Where a by-product or a lost component goes: a co-product (a product exchange), an emission
#: to air or water, wastewater to treatment or solid waste (technosphere outputs).
Fate = Literal["coproduct", "air", "water", "wastewater", "waste"]


class SourcedValue(Strict):
    """A value taken from a source (a publication, a patent, a BREF), cited."""

    value: FiniteFloat
    source: str = Field(min_length=3, description="The publication, page or table.")
    source_id: str | None = Field(
        default=None, description="Its entry in sources: when it is externally supplied data."
    )


class SourceRef(Strict):
    """A citation without a value: the source of a set of values (the selectivities)."""

    source: str = Field(min_length=3, description="The publication, page or table.")
    source_id: str | None = Field(
        default=None, description="Its entry in sources: when it is externally supplied data."
    )


class Byproduct(Strict):
    """What becomes of a product of the reactions other than the reference product."""

    fate: Fate
    reason: str = Field(default="", description="Why (a source, or the judgement).")
    properties: ProductProperties | None = Field(
        default=None, description="A co-product: what allocation weighs it by."
    )


class Losses(Strict):
    """How the unconverted input leaves: the defaults' split (air share, the rest to water)
    unless sourced here, or a fate per component (a gas that is vented, not drained)."""

    air: SourcedValue | None = Field(
        default=None, description="Fraction of each input's mass emitted to air."
    )
    water: Literal["wastewater", "water"] = Field(
        default="wastewater",
        description="The rest: wastewater to treatment (technosphere, default) or an emission "
        "to water.",
    )
    fate: dict[str, Fate] = Field(
        default_factory=dict,
        description="Component -> where all of its unconverted input goes, instead of the split.",
    )
    reason: str = Field(default="", description="Why the fates differ from the split.")

    @model_validator(mode="after")
    def _why(self) -> Losses:
        if self.air is not None and not 0 <= self.air.value <= 1:
            raise ValueError(f"losses.air is a fraction in [0, 1], not {self.air.value:g}")
        if self.fate and not self.reason:
            raise ValueError("losses.fate records its reason")
        if "coproduct" in self.fate.values():
            raise ValueError("an unconverted input is not a co-product")
        return self


class EstimateExchange(Strict):
    """A further exchange per kg of the reference product, taken from a source (Tier 1:
    auxiliaries, utilities, emissions of a BREF or a patent)."""

    key: str = Field(pattern=r"^[a-z][a-z-]*:[A-Za-z0-9_.\-]+$")
    title: str = ""
    type: Literal["input", "output", "emission", "resource"]
    amount: FiniteFloat
    unit: str
    component: str | None = Field(
        default=None, description="Its component (materials.yaml): it then counts in the balance."
    )
    cas: str | None = None
    carrier: Carrier | None = None
    link: Background | None = None
    source: str = Field(min_length=3)
    source_id: str | None = None


class LciEstimate(Strict):
    """An LCI estimate (``kind: lci_estimate``, ``lca/estimate.yaml``): what ``cheme assess
    lci-estimate`` builds a Tier 0 or Tier 1 dataset from (pre-release issue 182).

    The reactions of ``process/reactions.yaml`` named in ``reactions`` form the reference
    ``product`` (a component of ``process/materials.yaml``); ``yield`` is the efficiency over
    the whole scheme, ``key`` and ``selectivity`` fix the extents of several reactions. What it
    does not give comes from the versioned defaults (``data/tier-defaults.yaml``), marked
    assumed. Tier 1 takes the yield, electricity and heat from sources."""

    schema_: str = Field(alias="schema", description=f"Always {ESTIMATE_SCHEMA}.")
    kind: Literal["lci_estimate"]
    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    title: str = ""
    description: str = ""
    tier: Literal[0, 1]
    product: str = Field(description="The reference product: a component id.")
    reactions: list[str] = Field(min_length=1, description="Reaction ids of reactions.yaml.")
    key: str | None = Field(default=None, description="The key reactant (several reactions).")
    selectivity: dict[str, Annotated[FiniteFloat, Field(ge=0)]] = Field(
        default_factory=dict,
        description="kmol of each product per kmol of the key converted (several reactions).",
    )
    selectivity_source: SourceRef | None = Field(
        default=None,
        description="Where the selectivities come from. Tier 1 with several reactions requires "
        "it; without one the amounts that depend on them are assumed, not calculated.",
    )
    yield_: SourcedValue | None = Field(
        default=None,
        alias="yield",
        description="Efficiency over the whole scheme (0-1]; unset: the default (Tier 0).",
    )
    byproducts: dict[str, Byproduct] = Field(
        default_factory=dict, description="Component -> its fate; every by-product needs one."
    )
    losses: Losses = Field(default_factory=Losses)
    electricity: SourcedValue | None = Field(
        default=None, description="kWh per kg of product; unset: the default (Tier 0)."
    )
    heat: SourcedValue | None = Field(
        default=None, description="kWh per kg of product; unset: the default (Tier 0)."
    )
    exchanges: list[EstimateExchange] = Field(default_factory=list)
    origin: CarbonOrigin = Field(
        default="fossil", description="The carbon origin of carbon-bearing emissions."
    )
    location: str = ""
    year: int | None = Field(default=None, ge=1900, le=2200)
    technology: str = ""
    documentation: DatasetDocumentation | None = Field(
        default=None, description="The dataset's documentation (uuid, geography, review, ...)."
    )
    sources: list[Source] = Field(default_factory=list)
    output: str = Field(
        default="", description="Where the dataset is written; default lca/datasets/<id>.yaml."
    )

    @model_validator(mode="after")
    def _tier(self) -> LciEstimate:
        if self.schema_ != ESTIMATE_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, ESTIMATE_SCHEMA))
        if self.yield_ is not None and not 0 < self.yield_.value <= 1:
            raise ValueError(f"yield is a fraction in (0, 1], not {self.yield_.value:g}")
        if self.tier == 1:
            lacking = [n for n in ("yield_", "electricity", "heat") if getattr(self, n) is None]
            if lacking:
                names = ", ".join(n.rstrip("_") for n in lacking)
                raise ValueError(
                    f"a Tier 1 estimate takes {names} from a source (tier: 0 uses the defaults)"
                )
        if len(self.reactions) > 1 and (self.key is None or not self.selectivity):
            raise ValueError("several reactions need key and selectivity")
        if self.tier == 1 and len(self.reactions) > 1 and self.selectivity_source is None:
            raise ValueError("a Tier 1 estimate with several reactions takes selectivity_source")
        for name in ("electricity", "heat"):
            given = getattr(self, name)
            if given is not None and given.value < 0:
                raise ValueError(f"{name} must not be negative, not {given.value:g} kWh/kg")
        if self.product in self.byproducts:
            raise ValueError(f"{self.product} is the reference product, not a by-product")
        known = {s.id for s in self.sources}
        cited = [
            self.yield_,
            self.electricity,
            self.heat,
            self.losses.air,
            self.selectivity_source,
            *self.exchanges,
        ]
        stray = sorted({c.source_id for c in cited if c is not None and c.source_id} - known)
        if stray:
            raise ValueError(f"source_id not in sources: {', '.join(stray)}")
        return self


Allocation.model_rebuild()
LcaFile.model_rebuild()
