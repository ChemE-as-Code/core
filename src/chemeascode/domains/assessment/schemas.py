"""``estimate/rates.yaml`` (kind ``rates``): the unit rates and factors of a plant's estimate.

Every number in it is the project's own: cheme-as-code ships no prices. A rate prices one category
of the material take-off (``cheme assess mto``) per unit; the factors turn the priced
materials into an estimate by the factor method (installation on the materials, indirects on
the direct cost, contingency on the total). Each rate and factor states its ``status``,
``source`` and ``year``, so a reader can tell an assumption from a quotation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from chemeascode.foundation.schema_base import Strict, optional_schema

#: The categories of the material take-off, with the unit each one is counted in.
CATEGORY_UNITS = {
    "pipe": "m",
    "elbow": "ea",
    "tee": "ea",
    "reducer": "ea",
    "flange": "ea",
    "gasket": "ea",
    "valve": "ea",
    "inline": "ea",
    "steel": "t",
    "grating": "m2",
    "insulation": "m2",
    "concrete": "m3",
}
Category = Literal[
    "pipe",
    "elbow",
    "tee",
    "reducer",
    "flange",
    "gasket",
    "valve",
    "inline",
    "steel",
    "grating",
    "insulation",
    "concrete",
]
#: ``ASSUMED`` until a quotation or a priced contract backs the number (``QUOTED``).
RateStatus = Literal["ASSUMED", "QUOTED"]


class RateWhere(Strict):
    """Which take-off rows of the rate's category it prices; every given filter must match."""

    item: str | None = Field(
        default=None,
        description="Glob on the row's item (pipe, elbow 90, tee, reducing tee, the valve's DEXPI "
        "class such as BallValve, the steel section such as HEB300, plinth, ...).",
    )
    dn_min: float | None = Field(default=None, ge=0, description="Smallest DN priced.")
    dn_max: float | None = Field(default=None, ge=0, description="Largest DN priced.")
    pipe_class: str | None = Field(
        default=None, alias="class", description="Glob on the pipe class code (e.g. PN16, A1*)."
    )
    spec: str | None = Field(
        default=None,
        description="Glob on the row's spec (insulation of a pipe, material of a member).",
    )
    group: str | None = Field(
        default=None,
        description="Glob on the row's group (rack, structure, stair, ladder, platform, "
        "equipment, area, ...).",
    )


class Rate(Strict):
    """One unit rate: the price of one unit of the take-off rows it matches."""

    id: str = Field(min_length=1)
    category: Category
    unit: str = Field(description="Must be the category's take-off unit (m, ea, t, m2, m3).")
    rate: float = Field(ge=0, description="Price per unit, in the file's currency.")
    where: RateWhere = Field(default_factory=RateWhere)
    status: RateStatus = Field(description="ASSUMED, or QUOTED when a quotation backs it.")
    source: str = Field(min_length=3, description="Where the number comes from.")
    year: int = Field(ge=1900, le=2200, description="The year of the price.")
    notes: str | None = None

    @model_validator(mode="after")
    def _unit(self) -> Rate:
        expected = CATEGORY_UNITS[self.category]
        if self.unit != expected:
            raise ValueError(f"a {self.category} rate is per {expected}, not per {self.unit}")
        return self


class Factor(Strict):
    """One factor of the factor method.

    ``direct``: ``factor`` x the material cost of the categories in ``applies_to`` (all when
    empty),
    e.g. erection of piping. ``indirect``: ``factor`` x the direct cost (materials plus the
    direct factors), e.g. engineering. ``contingency``: ``factor`` x direct plus indirect cost.
    """

    id: str = Field(min_length=1)
    title: str | None = None
    kind: Literal["direct", "indirect", "contingency"]
    factor: float = Field(ge=0)
    applies_to: list[Category] = Field(
        default_factory=list,
        description="kind=direct: the categories whose material cost it multiplies (all when "
        "empty).",
    )
    status: RateStatus = "ASSUMED"
    source: str = Field(min_length=3)
    year: int = Field(ge=1900, le=2200)
    notes: str | None = None

    @model_validator(mode="after")
    def _on(self) -> Factor:
        if self.applies_to and self.kind != "direct":
            raise ValueError("only a direct factor applies to categories (applies_to:)")
        return self


class RateFile(Strict, optional_schema("rates")):
    """``estimate/rates.yaml``: the project's unit rates and estimate factors."""

    currency: str = Field(
        min_length=3, max_length=3, description="ISO 4217 code (XXX: no currency, an example)."
    )
    cost_year: int = Field(ge=1900, le=2200, description="The year the estimate is priced in.")
    example: bool = Field(
        default=False,
        description="True marks example numbers that price nothing: the estimate warns, and a "
        "gate requiring rates fails, until the project replaces them.",
    )
    basis: str | None = Field(default=None, description="What the estimate is for, its class.")
    rates: list[Rate] = Field(default_factory=list)
    factors: list[Factor] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> RateFile:
        for what, items in (("rate", self.rates), ("factor", self.factors)):
            seen: set[str] = set()
            for item in items:
                if item.id in seen:
                    raise ValueError(f"{what} id {item.id} appears twice")
                seen.add(item.id)
        return self


class CostIndex(Strict):
    """The cost index the project escalates the correlations' base year to: its value, the
    year (or month) it stands for, and where it is published."""

    value: float = Field(gt=0, description="e.g. the CEPCI of the estimate's cost year.")
    year: int = Field(ge=1900, le=2200)
    month: str | None = Field(default=None, description="e.g. annual, or 2026-06.")
    source: str = Field(min_length=3, description="Where the value is published.")


class EquipmentCostItem(Strict):
    """What the project states for one equipment item: a correlation or its size where the
    lists cannot give them, factors the package data lacks, or a cost of its own."""

    tag: str = Field(min_length=1)
    correlation: str | None = Field(
        default=None,
        description="A correlation id of the package data (cheme assess "
        "equipment --json lists them); default: chosen from the DEXPI class.",
    )
    size: float | None = Field(default=None, gt=0, description="The correlation's attribute A.")
    size_source: str | None = Field(default=None, description="Where the size comes from.")
    fm: float | None = Field(default=None, gt=0, description="Material factor Fm.")
    fp: float | None = Field(default=None, gt=0, description="Pressure factor Fp.")
    fbm: float | None = Field(default=None, gt=0, description="Bare module factor FBM.")
    factor_source: str | None = Field(
        default=None, description="Where fm, fp or fbm come from (a book, table, page)."
    )
    cost: float | None = Field(
        default=None,
        ge=0,
        description="The item's bare module cost from the project's own "
        "source (a quotation), in currency and year below; replaces the correlation.",
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    year: int | None = Field(default=None, ge=1900, le=2200)
    status: RateStatus | None = None
    source: str | None = Field(default=None, description="The cost's source.")
    exclude: str | None = Field(
        default=None,
        description="Leave the item out of the estimate, for this reason (a "
        "package unit costed by its vendor, an internal of another item).",
    )

    @model_validator(mode="after")
    def _check(self) -> EquipmentCostItem:
        if self.cost is not None and not (self.currency and self.year and self.source):
            raise ValueError(f"{self.tag}: a cost needs currency, year and source")
        if self.size is not None and not self.size_source:
            raise ValueError(f"{self.tag}: give size_source with size")
        if any(v is not None for v in (self.fm, self.fp, self.fbm)) and not self.factor_source:
            raise ValueError(f"{self.tag}: give factor_source with fm, fp or fbm")
        return self


class CostBasis(Strict, optional_schema("cost_basis")):
    """``estimate/cost-basis.yaml`` (kind ``cost_basis``): what the equipment estimate from
    the package's published correlations needs from the project."""

    cost_index: CostIndex | None = Field(
        default=None,
        description="The CEPCI to escalate to; without it costs stay at the correlations' "
        "base year (a finding).",
    )
    estimate_class: Literal[1, 2, 3, 4, 5] = Field(
        default=5,
        description="AACE 18R-97 class the estimate claims (default 5: equipment-factored, "
        "concept screening).",
    )
    items: list[EquipmentCostItem] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _unique(self) -> CostBasis:
        tags = [item.tag for item in self.items]
        if len(set(tags)) != len(tags):
            raise ValueError("a tag appears twice in items")
        return self
