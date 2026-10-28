"""Carbon accounting of LCI datasets (pre-release issue 181): carbon content, fossil and biogenic
carbon traced through the inputs, CCU and CCS, and the product carbon footprint breakdown.

A study that declares ``carbon_accounting:`` in ``lca/lca.yaml`` is a product carbon footprint
(PCF) in the sense of ISO 14067 and the TfS PCF Guideline v3. Everything here works on the
unallocated dataset (``kind: lci_dataset``) and on the allocated rows, never on the flowsheet.

**Carbon of an exchange** (kg C per kg, :func:`carbon_per_kg`): its ``carbon.total`` (filled from
the composition's formulas for a flowsheet-derived dataset, or given), else the formula of the
elementary flow by CAS number (CO2, CO, CH4), else that of CO2 for a captured CO2 feedstock
(``co2_source``) or a CO2 output to storage (``storage``). A material exchange without one is
listed as unknown and left out of the balance (never counted as 0 silently).

**Biogenic fraction of the carbon inputs**: a CO2 feedstock by its source (a fossil point
source is fossil, always; a biogenic point source or direct air capture is non-fossil under
``ccu_rule: cut-off`` and fossil under ``ccu_rule: upstream``, where the capture's benefit is
claimed upstream), an input with ``carbon.biogenic_fraction`` its declared fraction (read first,
for a resource too), an undeclared resource ``Carbon dioxide, in air`` is the biogenic uptake
(non-fossil), an input linked to another dataset carries that dataset's traced product fraction,
and any other carbon input, an undeclared carbon-bearing resource included, is fossil (the
conservative default: no removal without evidence; reported). Atmospheric carbon from direct
air capture is booked with the biogenic (non-fossil) carbon, as the ``Carbon dioxide, in air``
and ``Carbon dioxide, non-fossil`` flows of the reference lists do.

**Tracing** (:func:`trace`): each dataset is one well-mixed carbon pool. Outputs that declare
their biogenic fraction keep it; every other carbon output (products, wastes, CO2/CO/CH4
emissions, CO2 to storage) takes the fraction of what is left of the pool. Datasets referenced
through ``dataset:`` backgrounds are traced with it: the fractions of every dataset of the chain
solve one linear system (a carbon-flow matrix, as Carbon Minds describe for their supply chain
model, cm.chemicals methodology V2.03, here in our own implementation), so loops close. A plant
that burns a fossil fuel beside a biogenic feed declares its product's fraction where the one
pool would mix them (a documented simplification; tracing through the flowsheet's units is not
done yet).

:func:`split_emissions` then splits each CO2, CO and CH4 emission into its fossil and biogenic
part (``emission:<component>`` and ``emission:<component>.biogenic``), so that the climate
method characterises each by its origin. :func:`findings` checks the carbon balance (inputs
against products, outputs, emissions and storage), the declared biogenic contents against the
traced pool, CCU double counting and the declared origins. The interface to the element
balances of pre-release issue 174 is :class:`CarbonFlow`: kg of carbon and of biogenic carbon per
exchange.

**PCF** (:func:`pcf`), per functional unit, following the WBCSD PACT data model v2 and the TfS
PCF Guideline v3: fossil GHG emissions (direct fossil emissions and every background
contribution, which is taken as excluding biogenic CO2), direct land-use-change emissions,
other biogenic GHG emissions (biogenic CH4), the PCF excluding biogenic CO2 emissions and
removals, the biogenic carbon withdrawal (the product's biogenic carbon as CO2, <= 0), the PCF
including them, and the product's fossil and biogenic carbon content (kg C), always reported.
Cradle-to-gate, the -1 of every uptake and the +1 of every biogenic CO2 release cancel. What
does not cancel is biogenic carbon that does not leave as CO2: the carbon in the product (the
withdrawal), biogenic carbon in CH4, CO or a non-product output such as a waste or purge (its
uptake is booked, ``withdrawal_other``; the release of CH4 is charged at its own GWP in
``other_biogenic``, and that of CO is not charged: ASSUMED, no GWP is applied to CO), and, with
``ccs: technosphere``, the biogenic CO2 sent to storage:
including = excluding + withdrawal + withdrawal_other + stored biogenic CO2 (all <= 0). The
removals follow the carbon physically (the product's own biogenic carbon, not an allocated
share). Biogenic carbon of a purchased input is only as good as its declared fraction, and a
background factor that already credits an uptake is counted again: reported
(``cheme.lca-pcf-background-uptake``). Flows of origin ``land-use-change`` come from carbon
stocks, not from the inputs, and are left out of the carbon balance and the trace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from chemeascode.domains.assessment.lca.elementary import identities
from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.schemas import (
    CarbonAccounting,
    CarbonContent,
    DatasetExchange,
    LciDataset,
)
from chemeascode.domains.process.model import ATOMIC_MASS, element_flows
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.units import LCI_UNITS

_C, _O, _H = ATOMIC_MASS["C"], ATOMIC_MASS["O"], ATOMIC_MASS["H"]
#: kg CO2 per kg C.
CO2_PER_C = (_C + 2 * _O) / _C
#: Carbon-bearing elementary flows by CAS number: name and kg C per kg.
ELEMENTARY_CARBON: dict[str, tuple[str, float]] = {
    "124-38-9": ("carbon dioxide", _C / (_C + 2 * _O)),
    "630-08-0": ("carbon monoxide", _C / (_C + _O)),
    "74-82-8": ("methane", _C / (_C + 4 * _H)),
}
CO2_CAS = "124-38-9"
#: Relative tolerance of the carbon balance by maturity (process.yaml): the defaults
#: pre-release issue 174 proposes for its balance gates (<= 1 % for simulated designs, <= 5 % for
#: screening).
TOLERANCE = {"concept": 0.05, "screening": 0.05}
DEFAULT_TOLERANCE = 0.01
#: Suffix of the biogenic part of a split emission.
BIOGENIC_SUFFIX = ".biogenic"
#: Below this, a fraction counts as 0 (and above 1 minus it as 1).
EPS = 1e-9

#: Loads a referenced dataset by its path: the dataset, or why it does not load.
Load = Callable[[str], "LciDataset | str"]


@dataclass(frozen=True)
class CarbonFlow:
    """The carbon one exchange carries, per the dataset's basis."""

    key: str
    type: str
    #: kg of carbon, and of biogenic (non-fossil) carbon.
    carbon: float
    biogenic: float
    #: Where the biogenic fraction comes from: declared, co2-source, uptake, dataset <path>,
    #: assumed fossil, pool.
    how: str

    @property
    def fraction(self) -> float:
        return self.biogenic / self.carbon if self.carbon else 0.0


@dataclass
class CarbonTrace:
    """The carbon of one dataset: every carbon flow, the pool's biogenic fraction, and what
    could not be counted."""

    dataset: str
    basis: str
    flows: list[CarbonFlow] = field(default_factory=list)
    #: The biogenic fraction of the pool left for outputs that declare none (None: no carbon
    #: enters, or the declared outputs take more than enters).
    fraction: float | None = None
    #: Material exchanges whose carbon is unknown (left out of the balance).
    unknown: list[str] = field(default_factory=list)
    #: Carbon inputs counted as fossil for want of a declared fraction.
    assumed_fossil: list[str] = field(default_factory=list)
    #: The traced product fractions of the referenced datasets, by ``<path>#<product>``.
    upstream: dict[str, float] = field(default_factory=dict)
    #: What went wrong while tracing (a referenced dataset that does not load, ...).
    problems: list[str] = field(default_factory=list)

    def total(self, direction: str, biogenic: bool = False) -> float:
        """kg C (or biogenic kg C) entering (``in``) or leaving (``out``)."""
        side = ("input", "resource") if direction == "in" else ("product", "output", "emission")
        return sum(f.biogenic if biogenic else f.carbon for f in self.flows if f.type in side)

    @property
    def residual(self) -> float:
        """Carbon in minus carbon out, kg C per basis."""
        return self.total("in") - self.total("out")

    def flow(self, key: str) -> CarbonFlow | None:
        return next((f for f in self.flows if f.key == key), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "basis": self.basis,
            "unit": "kg C",
            "in": round(self.total("in"), 9),
            "out": round(self.total("out"), 9),
            "residual": round(self.residual, 9),
            "biogenic_in": round(self.total("in", True), 9),
            "biogenic_out": round(self.total("out", True), 9),
            "pool_biogenic_fraction": None if self.fraction is None else round(self.fraction, 6),
            "flows": [
                {**asdict(f), "carbon": round(f.carbon, 9), "biogenic": round(f.biogenic, 9)}
                for f in self.flows
            ],
            "unknown": list(self.unknown),
            "assumed_fossil": list(self.assumed_fossil),
            "upstream": {k: round(v, 6) for k, v in self.upstream.items()},
        }


def carbon_fractions(formulas: dict[str, str]) -> dict[str, float | None]:
    """Component id -> kg of carbon per kg of it, from its formula (*formulas*, e.g.
    ``Process.formulas()``); None when it has no formula the parser reads."""
    found: dict[str, float | None] = {}
    for name, formula in formulas.items():
        atoms = element_flows({name: 1.0}, {name: formula})
        mass = sum(ATOMIC_MASS[e] * n for e, n in atoms.items()) if atoms else 0.0
        found[name] = atoms.get("C", 0.0) * _C / mass if mass > 0 else None
    return found


def _counted(exchange: DatasetExchange) -> bool:
    """Exchanges of the operation that carry matter: not the construction, energy or a vent
    counted by its emissions (its components are exchanges of their own), nor an ``avoided:``
    credit (pre-release issue 180: a negative input standing for production avoided outside the
    plant; no carbon enters through it, and its output is already counted). A dataset counts mass in
    kg only (``INVENTORY_UNITS``), so t and g do not occur."""
    from chemeascode.domains.assessment.lca.allocation import _released

    return (
        exchange.phase == "operation"
        and exchange.unit == "kg"
        and not exchange.key.startswith("avoided:")
        and not _released(exchange)
    )


def _gas_volume(exchange: DatasetExchange) -> bool:
    """A material counted per gas volume (Nm3, Sm3): its carbon cannot be told without a molar
    mass, so it is listed as unknown rather than dropped from the balance silently."""
    from chemeascode.domains.assessment.lca.allocation import _released

    return (
        exchange.phase == "operation"
        and exchange.type in ("input", "resource", "product", "output", "emission")
        and LCI_UNITS.get(exchange.unit, ("", 0.0))[0] == "normal-volume"
        and not _released(exchange)
    )


def _stock_change(exchange: DatasetExchange) -> bool:
    """A flow of origin ``land-use-change``: its carbon comes from soil and biomass stocks, not
    from the carbon inputs of the process, so it takes no part in the carbon balance."""
    link = exchange.link
    return link is not None and link.elementary is not None and (
        link.elementary.origin == "land-use-change"
    )  # fmt: skip


def _carbon_output(exchange: DatasetExchange) -> bool:
    """An output, emission or product whose carbon leaves the process pool."""
    return (
        exchange.type in ("product", "output", "emission")
        and _counted(exchange)
        and not _stock_change(exchange)
    )


def carbon_per_kg(exchange: DatasetExchange) -> float | None:
    """kg of carbon per kg of *exchange*, or None when it is not known."""
    if exchange.carbon is not None and exchange.carbon.total is not None:
        return exchange.carbon.total
    if exchange.type in ("emission", "resource") and exchange.cas:
        found = ELEMENTARY_CARBON.get(normalise_cas(exchange.cas))
        if found is not None:
            return found[1]
    if exchange.co2_source is not None or exchange.storage is not None:
        return ELEMENTARY_CARBON[CO2_CAS][1]
    return None


def _declared(exchange: DatasetExchange) -> float | None:
    return exchange.carbon.biogenic_fraction if exchange.carbon is not None else None


def _input_fraction(
    exchange: DatasetExchange, accounting: CarbonAccounting | None
) -> tuple[float | None, str]:
    """The biogenic fraction of a carbon input that needs no other dataset, and how it was
    found; ``(None, "dataset <path>#<product>")`` for one linked to another dataset."""
    if exchange.co2_source is not None:
        if exchange.co2_source == "fossil-point-source":
            return 0.0, "co2-source fossil-point-source"
        rule = accounting.ccu_rule if accounting is not None else "cut-off"
        return (1.0 if rule == "cut-off" else 0.0), f"co2-source {exchange.co2_source} ({rule})"
    # a declared fraction wins over what the flow's kind would imply
    declared = _declared(exchange)
    if declared is not None:
        return declared, "declared"
    if exchange.type == "resource" and normalise_cas(exchange.cas or "") == CO2_CAS:
        return 1.0, "uptake"  # carbon dioxide, in air
    if exchange.link is not None and exchange.link.dataset is not None:
        ref = exchange.link.dataset
        return None, f"dataset {ref.path}#{ref.product}"
    # any other carbon input, a carbon-bearing resource included, is fossil until declared
    return 0.0, "assumed fossil"


@dataclass
class _Node:
    """One dataset of the chain in the carbon-flow matrix."""

    path: str
    dataset: LciDataset
    #: (exchange, kg C, known fraction or None, linked node index or None, how)
    inputs: list[tuple[DatasetExchange, float, float | None, int | None, str]] = field(
        default_factory=list
    )
    unknown: list[str] = field(default_factory=list)


def _linked_product(node: _Node, product: str) -> DatasetExchange | None:
    return node.dataset.product(product)


def trace(
    dataset: LciDataset,
    accounting: CarbonAccounting | None = None,
    load: Load | None = None,
    path: str = "",
) -> CarbonTrace:
    """The carbon of *dataset* traced through its inputs and, by *load*, through the datasets
    its inputs reference (their chain solved as one linear system)."""
    result = CarbonTrace(dataset.id, dataset.basis)
    nodes: list[_Node] = []
    index: dict[str, int] = {}

    def add(where: str, ds: LciDataset) -> int:
        index[where] = len(nodes)
        node = _Node(where, ds)
        nodes.append(node)
        for exchange in ds.exchanges:
            if exchange.type in ("input", "resource") and _gas_volume(exchange):
                if carbon_per_kg(exchange) is None:
                    node.unknown.append(exchange.key)
                continue
            if exchange.type not in ("input", "resource") or not _counted(exchange):
                continue
            per_kg = carbon_per_kg(exchange)
            fraction, how = _input_fraction(exchange, accounting if where == path else None)
            linked = None
            if fraction is None:
                ref = exchange.link.dataset
                other = _resolve(ref.path)
                product = other.product(ref.product) if isinstance(other, LciDataset) else None
                if product is None:
                    why = other if isinstance(other, str) else f"no product {ref.product}"
                    result.problems.append(f"{exchange.key}: {ref.path}: {why}")
                    fraction, how = 0.0, "assumed fossil"
                else:
                    if per_kg is None:
                        per_kg = carbon_per_kg(product)
                    linked = index[ref.path] if ref.path in index else add(ref.path, other)
            if per_kg is None:
                node.unknown.append(exchange.key)
                continue
            if per_kg == 0:
                continue
            node.inputs.append((exchange, exchange.amount * per_kg, fraction, linked, how))
        return index[where]

    def _resolve(where: str) -> LciDataset | str:
        if load is None:
            return "no loader for referenced datasets"
        return load(where)

    add(path, dataset)
    fractions = _solve(nodes)
    root = nodes[0]
    result.unknown = list(root.unknown)
    for exchange, carbon, fraction, linked, how in root.inputs:
        if linked is not None:
            ref = exchange.link.dataset
            fraction = _product_fraction(nodes[linked], ref.product, fractions[linked])
            result.upstream[f"{ref.path}#{ref.product}"] = fraction
        if how == "assumed fossil":
            result.assumed_fossil.append(exchange.key)
        result.flows.append(CarbonFlow(exchange.key, exchange.type, carbon, carbon * fraction, how))
    pool = fractions[0]
    result.fraction = pool
    for exchange in dataset.exchanges:
        if _gas_volume(exchange) and carbon_per_kg(exchange) is None:
            result.unknown.append(exchange.key)
            continue
        if not _carbon_output(exchange):
            continue
        per_kg = carbon_per_kg(exchange)
        if per_kg is None:
            result.unknown.append(exchange.key)
            continue
        if per_kg == 0:
            continue
        carbon = exchange.amount * per_kg
        declared = _declared(exchange)
        if declared is not None:
            result.flows.append(
                CarbonFlow(exchange.key, exchange.type, carbon, carbon * declared, "declared")
            )
        else:
            # a pool outside 0..1 (declared outputs taking more than enters) is reported, and
            # the rest of the outputs keep a physical fraction
            share = min(1.0, max(0.0, pool)) if pool is not None else 0.0
            result.flows.append(
                CarbonFlow(exchange.key, exchange.type, carbon, carbon * share, "pool")
            )
    return result


def _pool(node: _Node) -> tuple[float, float, float]:
    """The carbon entering *node*, and the carbon and biogenic carbon of the outputs that
    declare their fraction."""
    entering = sum(c for _, c, _, _, _ in node.inputs)
    fixed = fixed_bio = 0.0
    for exchange in node.dataset.exchanges:
        if not _carbon_output(exchange):
            continue
        declared, per_kg = _declared(exchange), carbon_per_kg(exchange)
        if declared is not None and per_kg:
            fixed += exchange.amount * per_kg
            fixed_bio += exchange.amount * per_kg * declared
    return entering, fixed, fixed_bio


def _solve(nodes: list[_Node]) -> list[float | None]:
    """The rest-of-pool biogenic fraction of every node: for node m,
    ``(C_in - C_fixed) r_m - sum_k c_k g_k = B_known - B_fixed``, with g_k the traced fraction
    of the product a linked input k comes from (its declared fraction, or r of its node)."""
    n = len(nodes)
    a = np.zeros((n, n))
    b = np.zeros(n)
    free: list[bool] = []
    for m, node in enumerate(nodes):
        entering, fixed, fixed_bio = _pool(node)
        rest = entering - fixed
        if rest <= EPS * max(1.0, entering):
            a[m, m], b[m] = 1.0, 0.0
            free.append(False)
            continue
        free.append(True)
        a[m, m] += rest
        b[m] -= fixed_bio
        for exchange, carbon, fraction, linked, _ in node.inputs:
            if linked is None:
                b[m] += carbon * fraction
                continue
            product = _linked_product(nodes[linked], exchange.link.dataset.product)
            declared = _declared(product) if product is not None else None
            if declared is not None:
                b[m] += carbon * declared
            else:
                a[m, linked] -= carbon
    try:
        solved = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        solved = np.linalg.lstsq(a, b, rcond=None)[0]
    return [float(x) if ok else None for x, ok in zip(solved, free, strict=True)]


def _product_fraction(node: _Node, product: str, pool: float | None) -> float:
    exchange = _linked_product(node, product)
    declared = _declared(exchange) if exchange is not None else None
    if declared is not None:
        return declared
    return min(1.0, max(0.0, pool)) if pool is not None else 0.0


def _origin_split(exchange: DatasetExchange) -> bool:
    """A CO2, CO or CH4 emission characterised by its origin (fossil or biogenic)."""
    link = exchange.link
    return (
        exchange.type == "emission"
        and normalise_cas(exchange.cas or "") in ELEMENTARY_CARBON
        and link is not None
        and link.elementary is not None
        and link.elementary.origin in ("fossil", "biogenic")
        and link.elementary.compartment != "resource"
    )


def _with_origin(exchange: DatasetExchange, origin: str, amount: float, key: str, title: str):
    spec = exchange.link.elementary.model_copy(update={"origin": origin})
    flow, _ = identities(exchange.cas, spec)
    content = CarbonContent(
        total=carbon_per_kg(exchange),
        biogenic_fraction=1.0 if origin == "biogenic" else 0.0,
        source="traced from the carbon inputs (cheme assess lca)",
    )
    return exchange.model_copy(
        update={
            "key": key,
            "title": title,
            "amount": amount,
            "link": exchange.link.model_copy(update={"elementary": spec}),
            "flow": flow,
            "carbon": content,
            "formula": None,
        }
    )


def split_emissions(dataset: LciDataset, carbon: CarbonTrace) -> LciDataset:
    """*dataset* with each CO2, CO and CH4 emission given the origin the pool's traced
    fraction says: fossil, biogenic, or both (``<key>`` fossil and ``<key>.biogenic``)."""
    pool = carbon.fraction
    if pool is None:
        return dataset
    pool = min(1.0, max(0.0, pool))
    exchanges: list[DatasetExchange] = []
    for exchange in dataset.exchanges:
        if not _origin_split(exchange) or _declared(exchange) is not None:
            exchanges.append(exchange)
            continue
        title = exchange.title or exchange.key
        if pool <= EPS:
            exchanges.append(_with_origin(exchange, "fossil", exchange.amount, exchange.key, title))
        elif pool >= 1 - EPS:
            exchanges.append(
                _with_origin(exchange, "biogenic", exchange.amount, exchange.key, title)
            )
        else:
            exchanges.append(
                _with_origin(
                    exchange,
                    "fossil",
                    exchange.amount * (1 - pool),
                    exchange.key,
                    f"{title}, fossil",
                )
            )
            exchanges.append(
                _with_origin(
                    exchange,
                    "biogenic",
                    exchange.amount * pool,
                    exchange.key + BIOGENIC_SUFFIX,
                    f"{title}, biogenic",
                )
            )
    return dataset.model_copy(update={"exchanges": exchanges})


def contents(dataset: LciDataset, carbon: CarbonTrace) -> LciDataset:
    """*dataset* with every carbon output's ``carbon`` filled in from the trace (its total and
    its biogenic fraction), so that the products state their content."""
    exchanges = []
    for exchange in dataset.exchanges:
        flow = carbon.flow(exchange.key)
        if flow is None or exchange.type not in ("product", "output") or exchange.amount == 0:
            exchanges.append(exchange)
            continue
        given = exchange.carbon or CarbonContent()
        exchanges.append(
            exchange.model_copy(
                update={
                    "carbon": CarbonContent(
                        total=given.total
                        if given.total is not None
                        else flow.carbon / exchange.amount,
                        biogenic_fraction=round(flow.fraction, 9),
                        source=given.source or "traced from the carbon inputs (cheme assess lca)",
                    )
                }
            )
        )
    return dataset.model_copy(update={"exchanges": exchanges})


def findings(
    carbon: CarbonTrace,
    dataset: LciDataset,
    accounting: CarbonAccounting,
    file: str,
    maturity: str | None = None,
) -> list[Finding]:
    """What the carbon accounting of *dataset* reports: the balance, the declared biogenic
    contents against the pool, origins, CCU and CCS. Rules ``cheme.lca-carbon-*``."""
    found: list[Finding] = []
    tolerance = TOLERANCE.get(maturity or "", DEFAULT_TOLERANCE)

    def add(level: str, rule: str, message: str, hint: str, ids=()) -> None:
        found.append(Finding(file, level, rule, message, ids=list(ids), hint=hint))  # type: ignore[arg-type]

    for problem in carbon.problems:
        add(
            "warning",
            "cheme.lca-carbon-upstream",
            f"carbon trace: {problem}; its carbon counts as fossil",
            "check the dataset: background and its product",
        )
    if carbon.unknown:
        add(
            "info",
            "cheme.lca-carbon-unknown",
            f"carbon content unknown, left out of the carbon balance: {', '.join(carbon.unknown)}",
            "give the streams a composition with formulas (process/materials.yaml), or "
            "carbon_accounting.content.<key>.total (0 for carbon-free flows)",
            carbon.unknown,
        )
    entering, leaving = carbon.total("in"), carbon.total("out")
    scale = max(entering, leaving)
    if scale > 0 and abs(entering - leaving) > tolerance * scale:
        add(
            "warning",
            "cheme.lca-carbon-balance",
            f"carbon in {entering:.6g} kg C, out {leaving:.6g} kg C per {carbon.basis}: residual "
            f"{entering - leaving:+.6g} kg C ({(entering - leaving) / scale:+.1%}, tolerance "
            f"{tolerance:.0%})",
            "a carbon output (CO2, purge, waste) or input is missing, or a content is wrong",
        )
    bio_in, bio_out = carbon.total("in", True), carbon.total("out", True)
    if (carbon.fraction is not None and not -EPS <= carbon.fraction <= 1 + EPS) or (
        max(bio_in, bio_out) > 0 and abs(bio_in - bio_out) > tolerance * max(scale, EPS)
    ):
        add(
            "warning",
            "cheme.lca-carbon-biogenic",
            f"declared biogenic carbon contents do not match the inputs: biogenic carbon in "
            f"{bio_in:.6g} kg C (uptake and inputs), out {bio_out:.6g} kg C per {carbon.basis}",
            "check the biogenic_fraction of the products and inputs (carbon_accounting.content)",
        )
    if carbon.assumed_fossil:
        add(
            "info",
            "cheme.lca-carbon-assumed-fossil",
            "carbon inputs without a declared biogenic fraction count as fossil: "
            + ", ".join(carbon.assumed_fossil),
            "declare carbon_accounting.content.<feed>.biogenic_fraction where the carbon is "
            "biogenic (with its source)",
            carbon.assumed_fossil,
        )
    pool = carbon.fraction
    if not accounting.trace_emissions and pool is not None:
        wrong = [
            e.key
            for e in dataset.exchanges
            if _origin_split(e)
            and (
                (e.link.elementary.origin == "fossil" and pool > tolerance)
                or (e.link.elementary.origin == "biogenic" and pool < 1 - tolerance)
            )
        ]
        if wrong:
            add(
                "warning",
                "cheme.lca-carbon-origin",
                f"the traced carbon is {pool:.1%} biogenic, but these emissions are mapped with "
                f"another origin: {', '.join(wrong)}",
                "set trace_emissions: true, or map their origin to match the carbon inputs",
                wrong,
            )
    stored = [e.key for e in dataset.exchanges if e.storage is not None]
    if stored and accounting.ccs == "emitted":
        add(
            "info",
            "cheme.lca-ccs-emitted",
            f"CO2 to storage counted as emitted (ccs: emitted): {', '.join(stored)}",
            "ccs: technosphere once the storage's permanence is shown",
            stored,
        )
    return found


def _kg_co2e(unit: str) -> float | None:
    """kg CO2-eq per unit of a climate category's unit (kg or t CO2-eq), else None."""
    text = unit.lower().replace(" ", "")
    if text.startswith("kg"):
        return 1.0
    if text.startswith("t"):
        return 1000.0
    return None


@dataclass
class Pcf:
    """The product carbon footprint breakdown per functional unit (kg CO2-eq unless named kg C
    or kg CO2), after ISO 14067, the TfS PCF Guideline v3 and the PACT data model v2."""

    category: str
    unit: str
    functional_unit: str
    biogenic_method: str
    ccu_rule: str
    ccs: str
    #: Fossil GHG emissions: direct fossil emissions and every background contribution.
    fossil: float = 0.0
    #: Direct land-use change emissions.
    dluc: float = 0.0
    #: Biogenic GHG emissions other than CO2 (biogenic CH4).
    other_biogenic: float = 0.0
    #: Biogenic CO2 as the method characterises it (0 under the neutrality convention).
    biogenic_co2_characterised: float = 0.0
    excluding: float = 0.0
    #: The product's biogenic carbon as CO2 (<= 0).
    withdrawal: float = 0.0
    #: The uptake of biogenic carbon that leaves as CH4, CO or in a non-product output (<= 0),
    #: as CO2: -44/12 x that carbon. Its release is not booked as CO2 (CH4 is in other_biogenic).
    withdrawal_other: float = 0.0
    #: Biogenic CO2 sent to permanent storage, as CO2 (<= 0; ccs technosphere).
    stored_biogenic: float = 0.0
    including: float = 0.0
    #: kg C per functional unit in the product, its biogenic and its fossil part.
    product_carbon: float = 0.0
    biogenic_carbon: float = 0.0
    fossil_carbon: float = 0.0
    #: kg C per functional unit of the product's carbon that comes from captured CO2 (CCU), and
    #: of that the part from a biogenic point source or the air (TfS v3 5.2.10.4: reported
    #: separately). A well-mixed pool: the share of captured CO2 in the carbon inputs.
    ccu_carbon: float = 0.0
    ccu_non_fossil_carbon: float = 0.0
    #: kg CO2 per functional unit (allocated): biogenic CO2 emitted and taken up in the
    #: foreground, and CO2 sent to storage.
    biogenic_co2_emitted: float = 0.0
    biogenic_co2_uptake: float = 0.0
    stored_co2: float = 0.0
    #: Exchanges whose climate impact came from a background (counted as fossil).
    background: list[str] = field(default_factory=list)
    #: Biogenic carbon inputs whose background has a negative climate impact: an uptake the
    #: background may already claim, which the withdrawal then counts again.
    background_uptake: list[str] = field(default_factory=list)
    #: Why the breakdown is incomplete or the numbers may not be exported.
    problems: list[str] = field(default_factory=list)

    @property
    def headline(self) -> float:
        """The PCF the study's biogenic method states: including (-1/+1) or excluding (0/0)."""
        return self.including if self.biogenic_method == "minus-one-plus-one" else self.excluding

    LINES = (
        ("fossil", "fossil GHG emissions", "kg CO2-eq"),
        ("dluc", "direct land-use change emissions", "kg CO2-eq"),
        ("other_biogenic", "biogenic GHG emissions other than CO2", "kg CO2-eq"),
        ("excluding", "PCF excluding biogenic CO2 emissions and removals", "kg CO2-eq"),
        ("withdrawal", "biogenic carbon withdrawal (the product's biogenic carbon)", "kg CO2-eq"),
        (
            "withdrawal_other",
            "uptake of biogenic carbon leaving as CH4, CO or in a non-product output",
            "kg CO2-eq",
        ),
        ("stored_biogenic", "biogenic CO2 to permanent storage (CCS)", "kg CO2-eq"),
        ("including", "PCF including biogenic CO2 emissions and removals", "kg CO2-eq"),
        ("product_carbon", "carbon content of the product", "kg C"),
        ("biogenic_carbon", "biogenic carbon content of the product", "kg C"),
        ("fossil_carbon", "fossil carbon content of the product", "kg C"),
        ("ccu_carbon", "carbon content of the product from captured CO2 (CCU)", "kg C"),
        (
            "ccu_non_fossil_carbon",
            "of which from a biogenic point source or the air (DAC)",
            "kg C",
        ),
        ("biogenic_co2_emitted", "biogenic CO2 emitted in the foreground", "kg CO2"),
        ("biogenic_co2_uptake", "biogenic CO2 taken up in the foreground", "kg CO2"),
        ("stored_co2", "CO2 sent to geological storage", "kg CO2"),
    )

    def lines(self) -> list[tuple[str, str, float, str]]:
        """(id, label, value, unit) of every line, in reporting order."""
        return [(k, label, getattr(self, k), unit) for k, label, unit in self.LINES]

    def as_dict(self) -> dict[str, Any]:
        return {
            **{k: (round(v, 9) if isinstance(v, float) else v) for k, v in asdict(self).items()},
            "headline": round(self.headline, 9),
        }


def pcf(
    inventory: Any,
    impacts: list[Any],
    category: Any,
    accounting: CarbonAccounting,
    carbon: CarbonTrace,
    product: str,
) -> Pcf:
    """The PCF breakdown of the functional unit (of *product*) of *inventory* (allocated) from
    its *impacts* in the climate *category* (baseline) and its *carbon* trace."""
    fu = inventory.functional_unit
    found = Pcf(category.id, category.unit, fu, accounting.biogenic, accounting.ccu_rule,
                accounting.ccs)  # fmt: skip
    to_kg = _kg_co2e(category.unit)
    if to_kg is None:
        found.problems.append(f"category {category.id} is in {category.unit}, not kg CO2-eq")
        to_kg = 1.0
    rows = {r.key: r for r in inventory.rows}
    flows = {f.key: f for f in carbon.flows}
    exchanges = {e.key: e for e in inventory.dataset.exchanges}
    for impact in impacts:
        value = impact.value * to_kg
        row = rows.get(impact.key)
        cas = normalise_cas(row.cas or "") if row is not None else ""
        if row is not None and row.kind == "resource" and cas == CO2_CAS:
            # the uptake of CO2 is a biogenic term: the removal is booked once, through the
            # product's biogenic carbon (the withdrawal), never as a fossil credit
            found.biogenic_co2_characterised += value
            continue
        background = inventory.backgrounds.get(impact.key)
        spec = background.elementary if background is not None else None
        if spec is None:
            found.fossil += value
            if impact.key not in found.background:
                found.background.append(impact.key)
            flow = flows.get(impact.key)
            exchange = exchanges.get(impact.key)
            if (
                value < 0
                and flow is not None
                and flow.type in ("input", "resource")
                and flow.biogenic > EPS
                and (exchange is None or exchange.co2_source is None)  # ccu_findings has those
                and impact.key not in found.background_uptake
            ):
                found.background_uptake.append(impact.key)
            continue
        if spec.origin == "land-use-change":
            found.dluc += value
        elif spec.origin == "biogenic" and cas == CO2_CAS:
            found.biogenic_co2_characterised += value
        elif spec.origin == "biogenic":
            found.other_biogenic += value
        else:
            found.fossil += value
    for row in inventory.rows:
        if row.phase != "operation":
            continue
        background = inventory.backgrounds.get(row.key)
        spec = background.elementary if background is not None else None
        co2 = normalise_cas(row.cas or "") == CO2_CAS
        if row.kind == "emission" and spec is not None and spec.origin == "biogenic" and co2:
            found.biogenic_co2_emitted += row.quantity
        if row.kind == "resource" and co2:
            found.biogenic_co2_uptake += row.quantity
    stored = [e for e in inventory.dataset.exchanges if e.storage is not None]
    for exchange in stored:
        row = rows.get(exchange.key)
        flow = flows.get(exchange.key)
        if row is None or flow is None or not exchange.amount:
            continue
        co2 = row.quantity * (flow.carbon / exchange.amount) * CO2_PER_C
        found.stored_co2 += co2
        biogenic_co2 = co2 * flow.fraction
        if accounting.ccs == "technosphere":
            found.stored_biogenic -= biogenic_co2
        else:  # counted as emitted, with its origin
            found.fossil += co2 - biogenic_co2
            found.biogenic_co2_emitted += biogenic_co2
    # the uptake of biogenic carbon that leaves as CH4, CO or in a waste or purge output is
    # booked like the product's: its release is no CO2 emission (biogenic CH4 is charged at its
    # own GWP in other_biogenic), so the -1 of its uptake does not cancel
    for exchange in inventory.dataset.exchanges:
        row, flow = rows.get(exchange.key), flows.get(exchange.key)
        if (
            exchange.type not in ("emission", "output")
            or exchange.storage is not None
            or (exchange.type == "emission" and normalise_cas(exchange.cas or "") == CO2_CAS)
            or _stock_change(exchange)
            or row is None
            or flow is None
            or not exchange.amount
            or flow.biogenic <= EPS
        ):
            continue
        found.withdrawal_other -= CO2_PER_C * row.quantity * flow.biogenic / exchange.amount
    reference = inventory.dataset.product(product)
    flow = flows.get(reference.key) if reference is not None else None
    if reference is not None and reference.unit != "kg":
        found.problems.append(
            f"{reference.key}: counted in {reference.unit}: the carbon content of a product "
            "not counted in kg is not traced"
        )
    elif reference is not None and reference.amount > 0:
        if flow is None and carbon_per_kg(reference) is None:
            found.problems.append(f"{reference.key}: carbon content unknown")
        elif flow is not None:
            per_kg = flow.carbon / reference.amount
            found.product_carbon = per_kg * inventory.amount
            found.biogenic_carbon = found.product_carbon * flow.fraction
            found.fossil_carbon = found.product_carbon - found.biogenic_carbon
    entering = carbon.total("in")
    if entering > 0 and found.product_carbon:
        captured = {e.key: e.co2_source for e in exchanges.values() if e.co2_source is not None}
        found.ccu_carbon = found.product_carbon * (
            sum(f.carbon for f in carbon.flows if f.key in captured) / entering
        )
        found.ccu_non_fossil_carbon = found.product_carbon * (
            sum(
                f.carbon
                for f in carbon.flows
                if captured.get(f.key) in ("biogenic-point-source", "direct-air-capture")
            )
            / entering
        )
    found.excluding = found.fossil + found.dluc + found.other_biogenic
    found.withdrawal = -CO2_PER_C * found.biogenic_carbon
    found.including = (
        found.excluding + found.withdrawal + found.withdrawal_other + found.stored_biogenic
    )
    if found.excluding < 0 or found.fossil < 0:
        found.problems.append(
            "the PCF excluding biogenic CO2 or the fossil emissions are negative (credits, e.g. "
            "substitution): PACT requires values >= 0"
        )
    return found


def pcf_findings(found: Pcf, file: str) -> list[Finding]:
    """Biogenic CO2 that the climate factors characterise (uptake or release with a non-zero
    factor): the PCF takes the climate factors as excluding biogenic CO2 and books the removals
    through the product's carbon, so this amount is left out of it (``cheme.lca-pcf-biogenic``)."""
    warned: list[Finding] = []
    if found.background_uptake:
        warned.append(
            Finding(
                file,
                "warning",
                "cheme.lca-pcf-background-uptake",
                "these carbon inputs carry biogenic carbon, and their background has a negative "
                f"climate impact: {', '.join(found.background_uptake)}. Background contributions "
                "count as fossil and exclude biogenic CO2; if the factor already credits the "
                "biogenic uptake, the withdrawal counts it again",
                ids=list(found.background_uptake),
                hint="use a background with biogenic CO2 characterised at 0 (IPCC without "
                "biogenic CO2), or take the credit out of the factor",
            )
        )
    if abs(found.biogenic_co2_characterised) <= EPS:
        return warned
    return warned + [
        Finding(
            file,
            "warning",
            "cheme.lca-pcf-biogenic",
            f"the climate category characterises biogenic CO2 uptake or release with "
            f"{found.biogenic_co2_characterised:+.6g} kg CO2-eq per {found.functional_unit}; the "
            "PCF assumes the climate factors exclude biogenic CO2, so this is left out of it "
            "(the removal is counted once, through the product's biogenic carbon)",
            hint="use a climate method with biogenic CO2 at 0 for the uptake and the biogenic "
            "emissions, or check the factor of the CO2 flow",
        )
    ]


def ccu_findings(
    inventory: Any, impacts: list[Any], accounting: CarbonAccounting, file: str
) -> list[Finding]:
    """A captured CO2 feedstock counted as a removal twice: its background already claims the
    removal (a negative climate impact) while ``ccu_rule: cut-off`` traces its non-fossil
    carbon into the product (``cheme.lca-ccu-double-count``)."""
    if accounting.ccu_rule != "cut-off" or inventory.dataset is None:
        return []
    captured = {
        e.key
        for e in inventory.dataset.exchanges
        if e.co2_source in ("biogenic-point-source", "direct-air-capture")
    }
    negative = sorted({i.key for i in impacts if i.key in captured and i.value < 0})
    if not negative:
        return []
    return [
        Finding(
            file,
            "warning",
            "cheme.lca-ccu-double-count",
            f"captured CO2 whose background is negative (a removal claimed upstream) while "
            f"ccu_rule cut-off claims it through the product: {', '.join(negative)}",
            ids=negative,
            hint="use a background for the capture without the removal, or ccu_rule: upstream",
        )
    ]
