"""Allocation: an unallocated LCI dataset, per functional unit of one of its products.

:func:`allocate` takes a dataset (``kind: lci_dataset``, derived from a plant or written by
hand) and the choice of a study (:class:`~.schemas.Allocation`) and gives the inventory per
functional unit. The dataset is never changed: the same unallocated inventory serves every
method and every study that references it.

- ``mass``, ``economic``, ``energy``, ``exergy``, ``shares``: each product gets a weight (its
  amount; x price; x energy content; its exergy; the given fraction); the functional unit's
  product carries ``weight / sum of weights`` of every non-product exchange;
- ``substitution``: the functional unit's product carries everything, and each other product is
  credited with the production it avoids (``substitution:<product>`` rows, negative quantities,
  the study's background for it);
- ``none``: the functional unit's product carries everything.

:func:`weights` gives the shares of a method, or why it cannot apply (a price, an energy
content or an exergy missing); :func:`applicable` the methods a study can compare.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chemeascode.domains.assessment.lca.schemas import (
    ALLOCATION_METHODS,
    Allocation,
    Background,
    DatasetExchange,
    LciDataset,
    ProductProperties,
)

#: Methods that share the burdens in proportion to a weight of each product.
PROPORTIONAL = ("mass", "economic", "energy", "exergy", "shares")


@dataclass(frozen=True)
class AllocatedRow:
    """One exchange per functional unit (see :class:`~.inventory.InventoryRow`)."""

    key: str
    title: str
    direction: str
    kind: str
    #: The dataset's amount (its basis), and its unit per the basis (e.g. kg/h).
    plant: float
    plant_unit: str
    quantity: float
    unit: str
    provenance: str
    streams: tuple[str, ...] = ()
    mapping: str = ""
    phase: str = "operation"
    #: An emission's CAS number (elementary characterisation).
    cas: str | None = None


@dataclass
class Allocated:
    """The inventory per functional unit and the shares that made it."""

    method: str
    #: Each product's share of the burdens (sums to 1).
    shares: dict[str, float] = field(default_factory=dict)
    rows: list[AllocatedRow] = field(default_factory=list)
    #: The background of every row that has one, by key.
    backgrounds: dict[str, Background] = field(default_factory=dict)
    #: Why the method cannot apply (then no rows).
    problem: str = ""


def describe(background: Background) -> str:
    """The mapping column of a background, e.g. ``factor:steel | activity:steel, low-alloyed``."""
    parts = []
    if background.factor is not None:
        parts.append(f"factor:{background.factor}")
    if background.activity is not None:
        where = f" [{background.activity.location}]" if background.activity.location else ""
        parts.append(f"activity:{background.activity.name}{where}")
    if background.biosphere is not None:
        parts.append(f"biosphere:{background.biosphere.name}")
    if background.dataset is not None:
        parts.append(f"dataset:{background.dataset.path}#{background.dataset.product}")
    if background.elementary is not None:
        e = background.elementary
        where = e.compartment + (
            "" if e.subcompartment == "unspecified" else f"/{e.subcompartment}"
        )
        parts.append(f"elementary:{where}, {e.origin}" + (f", {e.flow}" if e.flow else ""))
    return " | ".join(parts)


def _name(exchange: DatasetExchange) -> str:
    return exchange.key.split(":", 1)[1]


def properties(exchange: DatasetExchange, allocation: Allocation | None) -> ProductProperties:
    """A product's properties: the study's (``allocation.properties``, ``prices``) over the
    dataset's."""
    own = exchange.properties or ProductProperties()
    if allocation is None:
        return own
    given = allocation.product_properties(_name(exchange))
    return ProductProperties(
        price=given.price if given.price is not None else own.price,
        energy=given.energy if given.energy is not None else own.energy,
        exergy=given.exergy if given.exergy is not None else own.exergy,
        source=given.source or own.source,
    )


def weights(
    products: list[DatasetExchange], target: str, method: str, allocation: Allocation | None
) -> tuple[dict[str, float] | None, str]:
    """The share of each product (by name) under *method*, or ``(None, why not)``."""
    names = [_name(p) for p in products]
    if names == [target]:
        return {target: 1.0}, ""  # one product: nothing to allocate, whatever the method
    if method in ("none", "substitution"):
        return {n: 1.0 if n == target else 0.0 for n in names}, ""
    if method == "shares":
        given = allocation.shares if allocation else {}
        missing = [n for n in names if n not in given]
        if missing:
            return None, f"no share of {', '.join(missing)}"
        raw = {n: given[n] for n in names}
    else:
        raw = {}
        for product in products:
            name = _name(product)
            if method == "mass":
                if product.unit != "kg":
                    return None, f"{name} is counted in {product.unit}, not kg"
                raw[name] = product.amount
                continue
            props = properties(product, allocation)
            value = {"economic": props.price, "energy": props.energy, "exergy": props.exergy}[
                method
            ]
            if value is None:
                what = {"economic": "price", "energy": "energy content", "exergy": "exergy"}
                return None, f"no {what[method]} of {name}"
            raw[name] = product.amount * value
    total = sum(raw.values())
    if total <= 0 or raw.get(target, 0.0) <= 0:
        return None, f"{method} gives {target} no share"
    return {n: v / total for n, v in raw.items()}, ""


def applicable(
    dataset: LciDataset, target: str, allocation: Allocation | None
) -> list[tuple[str, dict[str, float] | None, str]]:
    """Every method with its shares, or why it does not apply (substitution: whether the study
    gives a background for every other product)."""
    products = dataset.products()
    found = []
    for method in ALLOCATION_METHODS:
        if method == "substitution":
            others = [_name(p) for p in products if _name(p) != target]
            given = allocation.substitution if allocation else {}
            missing = [n for n in others if n not in given]
            if missing:
                found.append((method, None, f"no substitute of {', '.join(missing)}"))
                continue
        shares, why = weights(products, target, method, allocation)
        found.append((method, shares, why))
    return found


def allocate(
    dataset: LciDataset,
    product: str,
    amount: float,
    method: str,
    allocation: Allocation | None = None,
    totals: dict[str, float] | None = None,
) -> Allocated:
    """The inventory of *dataset* per *amount* (in the product's unit) of *product* under
    *method*. *totals* gives, by phase, the factor from the dataset's basis to the plant's total
    for display (construction: hours x years)."""
    result = Allocated(method)
    target = dataset.product(product)
    if target is None:
        result.problem = f"{dataset.id} has no product {product}"
        return result
    name = _name(target)
    products = dataset.products()
    shares, why = weights(products, name, method, allocation)
    if shares is None:
        result.problem = why
        return result
    if target.amount <= 0:
        result.problem = f"{name} has no amount in {dataset.id}"
        return result
    result.shares = shares
    scale = shares[name] * amount / target.amount
    totals = totals or {}
    for exchange in dataset.exchanges:
        if exchange.type == "product":
            made = exchange.amount * amount / target.amount
            result.rows.append(
                AllocatedRow(
                    exchange.key,
                    exchange.title,
                    "output",
                    "energy" if exchange.unit == "kWh" else "material",
                    exchange.amount,
                    f"{exchange.unit}/h",
                    made,
                    exchange.unit,
                    exchange.provenance,
                    tuple(exchange.streams),
                    "coproduct",
                    exchange.phase,
                )
            )
            continue
        factor = totals.get(exchange.phase)
        plant, plant_unit = (
            (exchange.amount * factor, exchange.unit)
            if factor is not None
            else (exchange.amount, f"{exchange.unit}/h")
        )
        if exchange.free:
            mapping = "free"
        elif exchange.link is not None and exchange.link.missing:
            mapping = MISSING + exchange.link.missing
        elif exchange.link is not None:
            mapping = describe(exchange.link)
            result.backgrounds[exchange.key] = exchange.link
        else:
            mapping = (
                ("emission" if exchange.type == "output" else "resource")
                if _released(exchange)
                else ""
            )
        result.rows.append(
            AllocatedRow(
                exchange.key,
                exchange.title,
                "input" if exchange.type == "input" else "output",
                _kind(exchange),
                plant,
                plant_unit,
                exchange.amount * scale,
                exchange.unit,
                exchange.provenance,
                tuple(exchange.streams),
                mapping,
                exchange.phase,
                exchange.cas,
            )
        )
    if method == "substitution":
        for other in products:
            other_name = _name(other)
            if other_name == name:
                continue
            substitute = (allocation.substitution if allocation else {}).get(other_name)
            if substitute is None:
                result.problem = f"no substitute of {other_name}"
                result.rows = []
                return result
            key = f"substitution:{other_name}"
            background = substitute.background()
            if not background.missing:
                result.backgrounds[key] = background
            result.rows.append(
                AllocatedRow(
                    key,
                    f"Avoided: {other.title or other_name}",
                    "output",
                    "credit",
                    -other.amount,
                    f"{other.unit}/h",
                    -other.amount * amount / target.amount,
                    other.unit,
                    other.provenance,
                    tuple(other.streams),
                    MISSING + background.missing if background.missing else describe(background),
                    other.phase,
                )
            )
    return result


#: The mapping column of an exchange declared ``missing:``, before the reason.
MISSING = "missing: "

#: Marks an output released to the environment: counted by its emission:* exchanges.
RELEASED = "released to the environment"
#: Marks an input taken from nature: counted by its resource:* exchanges.
TAKEN = "taken from nature"


def _released(exchange: DatasetExchange) -> bool:
    """Released to the environment, or taken from nature: counted by its components."""
    return (exchange.type == "output" and exchange.source.startswith(RELEASED)) or (
        exchange.type == "input" and exchange.source.startswith(TAKEN)
    )


def _kind(exchange: DatasetExchange) -> str:
    if exchange.type in ("emission", "resource"):
        return exchange.type
    if exchange.unit == "tkm":
        return "transport"
    if exchange.phase in ("construction", "maintenance", "end-of-life"):
        return exchange.phase
    return "energy" if exchange.unit == "kWh" else "material"
