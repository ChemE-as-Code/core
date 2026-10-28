"""``process/design-basis.yaml``: what the plant must do. Free-form below the top level."""

from typing import Any

from pydantic import Field

from chemeascode.foundation.schema_base import Strict, optional_schema


class ResidenceTime(Strict):
    """A required liquid residence time of one item (``cheme datasheets fill`` checks it)."""

    tag: str = Field(description="Equipment-list tag.")
    minutes: float = Field(gt=0, description="Required residence time of the liquid outflow.")
    volume_fraction: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="Share of the vessel volume that counts as hold-up (e.g. up to the normal "
        "liquid level); 1: the whole volume, an upper bound.",
    )
    source: str = Field(default="", description="Where the requirement comes from.")


class DesignBasis(Strict, optional_schema("design_basis")):
    """Capacity, feeds, products, utilities and site. Values are free-form mappings; a feed or
    a product may name the flowsheet feed or product it is (``terminal``)."""

    capacity: dict[str, Any] = Field(default_factory=dict)
    feeds: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Free-form; terminal: the id of the flowsheet feed it is "
        "(process/flowsheet.yaml feeds[].id; cheme.contract-ref).",
    )
    products: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Free-form; terminal: the id of the flowsheet product it is "
        "(process/flowsheet.yaml products[].id; cheme.contract-ref).",
    )
    utilities: list[dict[str, Any]] = Field(default_factory=list)
    site: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    residence_times: list[ResidenceTime] = Field(
        default_factory=list,
        description="Required liquid residence times by tag, checked against the datasheets.",
    )
