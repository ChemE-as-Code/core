"""Schema ``cheme/catalysts/v1`` (``process/catalysts.yaml``) and the checks of a catalyst.

A catalyst is what a reactor's bed holds: its identity (active phase, promoters, support,
form), the physical data a bed is sized with (particle diameter and sphericity, bulk and
particle density, bed voidage, surface area), the window it is used in (temperature,
pressure, space velocity), what poisons it, how it deactivates and is regenerated, and what it
costs. Every block of data carries its provenance and source.

Rules (``cheme.catalyst-*``), each finding naming the file, line, rule and a hint:

- ``catalyst-schema``: the file does not follow ``cheme/catalysts/v1``;
- ``catalyst-duplicate-id``: two catalysts with one id;
- ``catalyst-density``: the bulk density is not below the particle density;
- ``catalyst-voidage`` (warning): the bed voidage differs from ``1 - bulk / particle density``
  by more than 0.05;
- ``catalyst-poison`` (info): a poison that is no declared component (it cannot be checked
  against the feeds);
- ``catalyst-unknown`` (warning, :func:`reference_rules`): a reaction's ``catalyst``, its rate
  law's ``rate.catalyst`` or its mechanism's ``mechanism.catalyst`` in
  ``process/reactions.yaml`` that is no catalyst id of this file (a reaction's own
  ``catalyst`` may also be a catalyst's ``name``: ``catalyst-by-name``, info). Without this
  file nothing is checked. A block's or step's ``catalyst`` is ``cheme.process-catalyst``
  (an error).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from chemeascode.domains.chemistry.reactions import REACTIONS_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Provenance, Strict, unsupported_schema
from chemeascode.foundation.yamlsource import _yaml_line

SCHEMA = "cheme/catalysts/v1"
CATALYSTS_FILE = "process/catalysts.yaml"


def _ordered(value: tuple[float, float] | None) -> tuple[float, float] | None:
    if value is not None and not value[0] < value[1]:
        raise ValueError("a range is (min, max) with min < max")
    return value


class SpaceVelocity(Strict):
    """The space velocity range the catalyst is used in, 1/h."""

    basis: Literal["GHSV", "WHSV", "LHSV"] = Field(
        description="GHSV: Nm3/h of gas per m3 of bed; WHSV: kg/h of feed per kg of catalyst; "
        "LHSV: m3/h of liquid per m3 of bed"
    )
    range: tuple[float, float] = Field(description="1/h, min and max")
    # left out of dumps when unset: catalysts written before keep their dumps and fingerprints
    gas: Literal["wet", "dry"] = Field(
        default="wet",
        description="GHSV: the gas the Nm3/h count, wet (with its water vapour) or dry (water "
        "left out)",
        exclude_if=lambda value: value == "wet",
    )
    provenance: Provenance
    source: str = ""

    @field_validator("range")
    @classmethod
    def _range(cls, value: tuple[float, float]) -> tuple[float, float]:
        return _ordered(value)  # type: ignore[return-value]

    @model_validator(mode="after")
    def _gas(self) -> SpaceVelocity:
        if self.gas == "dry" and self.basis != "GHSV":
            raise ValueError("gas: dry applies to a GHSV")
        return self


class Deactivation(Strict):
    """How the catalyst deactivates. With ``law``, its activity (rate over the fresh rate) after
    ``t`` hours on stream at the plant's conditions: ``first_order`` ``a = exp(-kd t)``;
    ``power`` ``da/dt = -kd a^order``, ``a = (1 + (order - 1) kd t)^(1 / (1 - order))``."""

    lifetime: float | None = Field(default=None, gt=0, description="years of service")
    mechanisms: list[str] = Field(
        default_factory=list, description="e.g. sintering, coking, poisoning, attrition"
    )
    regeneration: str = Field(default="", description="How, if at all (e.g. coke burn-off).")
    # left out of dumps when unset: catalysts written before keep their dumps and fingerprints
    law: Literal["first_order", "power"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    kd: float | None = Field(
        default=None,
        gt=0,
        description="1/h at the plant's conditions",
        exclude_if=lambda value: value is None,
    )
    order: float = Field(
        default=2.0,
        gt=1,
        description="power law: the order (above 1)",
        exclude_if=lambda value: value == 2.0,
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _law(self) -> Deactivation:
        if (self.law is None) != (self.kd is None):
            raise ValueError("an activity law needs kd, and kd a law")
        return self

    def activity(self, hours: float) -> float:
        """The activity after *hours* on stream (1 without a law)."""
        if self.law is None or self.kd is None or hours <= 0:
            return 1.0
        if self.law == "first_order":
            return math.exp(-self.kd * hours)
        return (1 + (self.order - 1) * self.kd * hours) ** (1 / (1 - self.order))


class Price(Strict):
    value: float = Field(gt=0)
    unit: Literal["USD/kg", "EUR/kg", "USD/m3", "EUR/m3"]
    year: int = Field(ge=1950, le=2100, description="The price's year (for escalation).")
    provenance: Provenance
    source: str = ""


class Physical(Strict):
    """Particle and bed data, SI units."""

    form: (
        Literal[
            "sphere",
            "pellet",
            "extrudate",
            "ring",
            "multi-hole",
            "granule",
            "monolith",
            "powder",
            "gauze",
        ]
        | None
    ) = None
    particle_diameter: float | None = Field(
        default=None, gt=0, description="m, the equivalent sphere's diameter"
    )
    sphericity: float | None = Field(default=None, gt=0, le=1)
    particle_density: float | None = Field(default=None, gt=0, description="kg/m3")
    bulk_density: float | None = Field(default=None, gt=0, description="kg/m3 of packed bed")
    bed_voidage: float | None = Field(default=None, gt=0, lt=1)
    surface_area: float | None = Field(default=None, gt=0, description="m2/g, BET")
    # transport in the particle (left out of dumps when unset: fingerprints stay as they were)
    porosity: float | None = Field(
        default=None, gt=0, lt=1, description="of the particle", exclude_if=lambda v: v is None
    )
    tortuosity: float | None = Field(
        default=None, ge=1, description="of the particle's pores", exclude_if=lambda v: v is None
    )
    effective_diffusivity: float | None = Field(
        default=None,
        gt=0,
        description="m2/s in the particle (instead of porosity, tortuosity and the bed's "
        "diffusivity)",
        exclude_if=lambda v: v is None,
    )
    provenance: Provenance
    source: str = ""


class Window(Strict):
    """Where the catalyst may be used."""

    temperature: tuple[float, float] | None = Field(default=None, description="K, min and max")
    pressure: tuple[float, float] | None = Field(default=None, description="kPa(a), min, max")
    provenance: Provenance
    source: str = ""

    @field_validator("temperature", "pressure")
    @classmethod
    def _range(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        return _ordered(value)


class Catalyst(Strict):
    """One catalyst: identity, physical data, window, poisons, deactivation, price."""

    id: str
    name: str = ""
    active_phase: str = Field(description="e.g. Fe (magnetite), Cu/ZnO, Ni, Ag, V2O5")
    promoters: list[str] = Field(default_factory=list)
    support: str = ""
    physical: Physical | None = None
    window: Window | None = None
    space_velocity: SpaceVelocity | None = None
    poisons: list[str] = Field(
        default_factory=list, description="Component ids where declared (checked in feeds)."
    )
    deactivation: Deactivation | None = None
    price: Price | None = None
    sources: list[str] = Field(default_factory=list, description="DOIs or references.")


class Catalysts(Strict):
    """The catalysts of the process."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["catalysts"]
    catalysts: list[Catalyst] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> Catalysts:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self

    def by_id(self) -> dict[str, Catalyst]:
        return {c.id: c for c in self.catalysts}


def rules(catalysts: Catalysts, doc: Any, components: Iterable[str]) -> list[Finding]:
    """Every ``cheme.catalyst-*`` finding of *catalysts*; *components*: the declared ids."""
    known = set(components)
    findings: list[Finding] = []

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        findings.append(
            Finding(
                CATALYSTS_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.catalyst-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    seen: set[str] = set()
    for i, cat in enumerate(catalysts.catalysts):
        loc = ["catalysts", i]
        if cat.id in seen:
            add(
                "error",
                "duplicate-id",
                f"catalyst {cat.id} is declared twice",
                loc,
                [cat.id],
                "give each catalyst its own id",
            )
        seen.add(cat.id)
        phys = cat.physical
        if phys is not None and phys.bulk_density and phys.particle_density:
            if phys.bulk_density >= phys.particle_density:
                add(
                    "error",
                    "density",
                    f"catalyst {cat.id}: bulk density {phys.bulk_density:g} kg/m3 is not below "
                    f"the particle density {phys.particle_density:g} kg/m3",
                    [*loc, "physical"],
                    [cat.id],
                    "the bulk density includes the voids between the particles",
                )
            elif phys.bed_voidage is not None:
                implied = 1.0 - phys.bulk_density / phys.particle_density
                if abs(implied - phys.bed_voidage) > 0.05:
                    add(
                        "warning",
                        "voidage",
                        f"catalyst {cat.id}: bed voidage {phys.bed_voidage:g}, but the densities "
                        f"give {implied:.3g}",
                        [*loc, "physical", "bed_voidage"],
                        [cat.id],
                        "check the densities or the voidage",
                    )
        for j, poison in enumerate(cat.poisons):
            if poison not in known:
                add(
                    "info",
                    "poison",
                    f"catalyst {cat.id}: poison {poison} is no declared component; it is not "
                    "checked against the feeds",
                    [*loc, "poisons", j],
                    [cat.id],
                    "name it by a component id of process/materials.yaml to have it checked",
                )
    return findings


def reference_rules(
    catalysts: Catalysts | None, reactions: Iterable[Any], doc: Any
) -> list[Finding]:
    """The ``cheme.catalyst-unknown`` and ``-by-name`` findings of the catalysts *reactions*
    (of ``process/reactions.yaml``, its YAML nodes *doc*) name: each must be an id of
    *catalysts*. None (no catalysts file): nothing is checked."""
    if catalysts is None:
        return []
    ids = {c.id for c in catalysts.catalysts}
    names = {c.name.strip().casefold(): c.id for c in catalysts.catalysts if c.name.strip()}
    declared = ", ".join(sorted(ids)) or "none"
    findings: list[Finding] = []
    for i, reaction in enumerate(reactions):
        loc = ["reactions", i]
        refs = [("catalyst", reaction.catalyst, [*loc, "catalyst"])]
        if reaction.rate is not None:
            refs.append(("rate.catalyst", reaction.rate.catalyst, [*loc, "rate", "catalyst"]))
        if reaction.mechanism is not None:
            refs.append(
                ("mechanism.catalyst", reaction.mechanism.catalyst, [*loc, "mechanism", "catalyst"])
            )
        for where, name, at in refs:
            if not name or name in ids:
                continue
            by_name = names.get(name.strip().casefold())
            if by_name is not None and where == "catalyst":
                level, rule = "info", "by-name"
                message = f"reaction {reaction.id}: catalyst {name!r} is catalyst {by_name}'s name"
                hint = f"write its id: catalyst: {by_name}"
            else:
                level, rule = "warning", "unknown"
                message = (
                    f"reaction {reaction.id}: {where} {name!r} is no catalyst of {CATALYSTS_FILE}"
                )
                hint = (
                    f"write its id: {by_name}"
                    if by_name is not None
                    else f"name a declared catalyst ({declared}), or declare it in {CATALYSTS_FILE}"
                )
            findings.append(
                Finding(
                    REACTIONS_FILE,
                    level,  # type: ignore[arg-type]
                    f"cheme.catalyst-{rule}",
                    message,
                    line=_yaml_line(doc, at),
                    ids=[reaction.id, name],
                    hint=hint,
                )
            )
    return findings
