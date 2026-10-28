"""Tiered LCI generation (pre-release issue 182): a screening dataset for a process without a
flowsheet.

:func:`lci_estimate` builds a ``kind: lci_dataset`` per kg of the reference product from an
estimate (``lca/estimate.yaml``, ``kind: lci_estimate``), the reactions of
``process/reactions.yaml`` and the formulas of ``process/materials.yaml``:

- **Tier 0, stoichiometric.** The screening approach of Hischier et al. (2005, Int J LCA
  10:59, section 2.3), as the ecoinvent chemicals reports apply it (Althaus et al. 2007): the
  reactants from the balanced reactions at an efficiency over the whole scheme (95 % unless a
  source gives the yield); the unconverted input split into an air share (0.2 % of the input
  mass) and the rest to water (wastewater to treatment by default: the library's cut-off model
  keeps treatment without recovery in the producer's system); electricity and heat from site
  averages. Every value comes from the versioned defaults file (``data/tier-defaults.yaml``),
  which gives each its source and whether the number was confirmed in that source.
- **Tier 1, sourced conceptual.** The yield, electricity and heat, and any further exchange,
  taken from open literature, patents or BREFs with their source; the loss split may still
  come from the defaults.

Every exchange that takes a default is ``provenance: assumed`` (origin ``design-rule``), cites
its rule in ``source`` and carries the rule's pedigree; ``generation`` records the tier, the
method, the defaults file's version and the rules used. The tier caps the dataset: maturity
``sourced`` at most (``balanced`` needs a flowsheet) and a pedigree floor per indicator, from
which the DQR floor follows. The element balance is mandatory: a dataset whose elements do not
close is not written (:mod:`.balance`).

:func:`tier_findings` checks a generated dataset (balance, default exchanges assumed, the
floor, a manifest maturity above the cap); :func:`compare_with_design` compares an estimate with
a flowsheet of the same process (the validation of the tiers against full designs).
"""

from __future__ import annotations

import functools
import hashlib
import json
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.assessment.lca.balance import ElementBalance, element_balance
from chemeascode.domains.assessment.lca.documentation import NAMESPACE, VALID_YEARS
from chemeascode.domains.assessment.lca.elementary import identities
from chemeascode.domains.assessment.lca.quality import score
from chemeascode.domains.assessment.lca.schemas import (
    DATASET_SCHEMA,
    TIER_MATURITY_CAP,
    Background,
    Carrier,
    DatasetDocumentation,
    DatasetExchange,
    DatasetProvenance,
    DatasetTime,
    Elementary,
    Generation,
    LciDataset,
    LciEstimate,
    Modelling,
    Pedigree,
    SystemBoundary,
)
from chemeascode.domains.process.screening_balance import (
    Chemistry,
    element_masses,
    load_chemistry,
    stoichiometric_balance,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision

ESTIMATE_FILE = "lca/estimate.yaml"
DATASETS_DIR = "lca/datasets"
DEFAULTS_FILE = Path(__file__).parent / "data" / "tier-defaults.yaml"
INPUTS = ("process/reactions.yaml", "process/materials.yaml")
#: The method each tier states.
METHODS = {
    0: "stoichiometric screening (Hischier et al. 2005; Althaus et al. 2007)",
    1: "sourced conceptual (yields, utilities and emissions from sources)",
}
#: The library manifest's ``maturity`` labels (``project.maturity.LIBRARY_MATURITY``), lowest
#: first, and the highest one a tier supports: ``sourced`` maps to ``concept``.
LIBRARY_MATURITY = (
    "concept",
    "screening",
    "basic-engineering",
    "detail-engineering",
    "operating-reference",
)
TIER_LIBRARY_CAP = {0: "concept", 1: "concept"}
#: Where each fate puts a component: (key prefix, key suffix, exchange type, compartment).
FATES = {
    "air": ("emission", "", "emission", "air"),
    "water": ("emission", "-to-water", "emission", "water"),
    "wastewater": ("wastewater", "", "output", None),
    "waste": ("waste", "", "output", None),
}
CARBON = "C"
#: A component whose normal boiling point is below this (K, 25 degC) is a gas at ambient
#: conditions: draining it as wastewater is physically doubtful.
AMBIENT_K = 298.15


# -- the defaults -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Default:
    """One default value of the defaults file."""

    id: str
    title: str
    value: float
    unit: str
    status: str
    source: str
    pedigree: tuple[int, ...]
    carrier: str = ""
    carrier_note: str = ""
    apply: bool = True


@dataclass(frozen=True)
class TierDefaults:
    """The defaults file: its id and version, the values and the floors per tier."""

    id: str
    version: str
    values: dict[str, Default]
    floors: dict[int, tuple[int, ...]]

    @property
    def label(self) -> str:
        return f"{self.id} {self.version}"

    def rule(self, name: str) -> str:
        return f"{self.label}: {name}"


@functools.cache
def tier_defaults() -> TierDefaults:
    """The packaged defaults (``data/tier-defaults.yaml``)."""
    data = yaml.safe_load(DEFAULTS_FILE.read_text(encoding="utf-8"))
    values = {
        name: Default(
            id=name,
            title=entry["title"],
            value=float(entry["value"]),
            unit=entry["unit"],
            status=entry["status"],
            source=" ".join(entry["source"].split()),
            pedigree=tuple(entry["pedigree"]),
            carrier=entry.get("carrier", ""),
            carrier_note=" ".join(entry.get("carrier_note", "").split()),
            apply=entry.get("apply", True),
        )
        for name, entry in data["defaults"].items()
    }
    floors = {int(t): tuple(v) for t, v in data["floors"].items()}
    return TierDefaults(data["id"], data["version"], values, floors)


def dqr_floor(floor: tuple[int, ...]) -> float:
    """The TfS DQR of a pedigree *floor*: the mean of its temporal, geographical and
    technological scores (TiR, GeR, TeR)."""
    return round((floor[2] + floor[3] + floor[4]) / 3, 4)


# -- the estimate -------------------------------------------------------------------------------


@dataclass
class EstimateResult:
    """The dataset an estimate gives, where it goes, its balance and what was found."""

    root: Path
    spec_path: str
    spec: LciEstimate | None = None
    dataset: LciDataset | None = None
    output: str = ""
    balance: ElementBalance | None = None
    findings: list[Finding] = field(default_factory=list)
    source: SourceRevision | None = None

    @property
    def loaded(self) -> bool:
        return self.dataset is not None and not any(f.level == "error" for f in self.findings)

    def to_json(self) -> str:
        """The dataset, where it goes, its balance, the findings and the source revision."""
        return json.dumps(
            {
                "spec": self.spec_path,
                "output": self.output,
                "dataset": self.dataset.model_dump(mode="json", by_alias=True, exclude_none=True)
                if self.dataset
                else None,
                "balance": self.balance.record().model_dump() if self.balance else None,
                "findings": [{**asdict(f), "id": f.id} for f in self.findings],
                "source": self.source.as_dict() if self.source else None,
            },
            indent=2,
        )


def _error(path: str, rule: str, message: str, hint: str = "") -> Finding:
    return Finding(path, "error", rule, message, hint=hint)


def load_estimate(root: Path, path: str) -> tuple[LciEstimate | None, list[Finding]]:
    """The estimate at *path* (from *root*), or the finding why it does not load."""
    from chemeascode.domains.assessment.lca.report import _load

    spec, _, found = _load(
        Path(root),
        path,
        LciEstimate,
        "cheme.lci-estimate-schema",
        "write it (cheme schema lci_estimate; docs/framework/lci-estimate.md)",
    )
    return spec, found


def lci_estimate(root: Path, path: str = ESTIMATE_FILE) -> EstimateResult:
    """The Tier 0 or Tier 1 dataset of the estimate at *path* in the repository at *root*,
    independent of the working directory. Input problems are findings; the dataset is set only
    when it validates and its element balance closes."""
    root = Path(root)
    result = EstimateResult(root, path, source=source_revision(root, [path, *INPUTS]))
    spec, found = load_estimate(root, path)
    result.findings += found
    if spec is None:
        return result
    result.spec = spec
    result.output = spec.output or f"{DATASETS_DIR}/{spec.id}.yaml"
    chemistry = load_chemistry(root)
    result.findings += [f for f in chemistry.findings if f.level == "error"]
    if any(f.level == "error" for f in result.findings):
        return result
    try:
        dataset = _build(spec, chemistry, tier_defaults(), path, result.findings)
    except ValueError as failure:
        result.findings.append(
            _error(
                path,
                "cheme.lci-estimate",
                f"{spec.id}: {failure}",
                hint="check the reactions, the product, the selectivity and the by-products' fates",
            )
        )
        return result
    files = {
        p: "sha256:" + hashlib.sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for p in (path, *INPUTS)
        if (root / p).is_file()
    }
    dataset = dataset.model_copy(
        update={"provenance": dataset.provenance.model_copy(update={"files": files})}
    )
    balance = element_balance(dataset)
    result.balance = balance
    if not balance.closed:
        result.findings.append(_unbalanced(path, balance))
        return result
    result.dataset = LciDataset.model_validate(
        dataset.model_copy(
            update={
                "generation": dataset.generation.model_copy(update={"balance": balance.record()})
            }
        ).model_dump(by_alias=True)
    )
    result.findings += tier_findings(result.dataset, result.output, owner_maturity(root))
    return result


def owner_maturity(root: Path) -> str | None:
    """The manifest ``maturity`` a generated dataset in the repository at *root* is checked
    against: the ``process.yaml`` label when the repository has no flowsheet, so that the
    manifest describes the process by its datasets; None when it has one, as the manifest's
    maturity then rests on the flowsheet (``cheme maturity``), not on a screening dataset that
    the study reads as a background."""
    from chemeascode.domains.assessment.lca.report import maturity
    from chemeascode.domains.process import FLOWSHEET_FILE

    root = Path(root)
    return None if (root / FLOWSHEET_FILE).is_file() else maturity(root)


def _unbalanced(path: str, balance: ElementBalance) -> Finding:
    detail = ", ".join(
        f"{e} in {i:.6g} kg, out {o:.6g} kg" for e, (i, o) in balance.unbalanced().items()
    )
    return _error(
        path,
        "cheme.lci-unbalanced",
        f"the element balance does not close: {detail or 'no element counted'}",
        hint="every material exchange names its component (generation.components) with a "
        "formula; check the stoichiometry and the fates",
    )


class _Exchanges:
    """The exchanges being built, keyed, with the component and formula of each."""

    def __init__(self, chemistry: Chemistry, origin: str) -> None:
        self.chemistry = chemistry
        self.origin = origin
        self.items: dict[str, DatasetExchange] = {}
        self.components: dict[str, str] = {}
        self.used: list[str] = []

    def use(self, rule: str) -> None:
        if rule not in self.used:
            self.used.append(rule)

    def add(self, exchange: DatasetExchange, component: str | None = None) -> None:
        old = self.items.get(exchange.key)
        if old is not None:
            # one component reaching one fate twice (a by-product and its unconverted feed)
            weaker = (
                "assumed" if "assumed" in (old.provenance, exchange.provenance) else "calculated"
            )
            exchange = old.model_copy(
                update={
                    "amount": old.amount + exchange.amount,
                    "provenance": weaker,
                    "origin": old.origin if old.origin == exchange.origin else None,
                    "source": f"{old.source}; {exchange.source}",
                    "source_id": old.source_id if old.source_id == exchange.source_id else None,
                    "pedigree": old.pedigree if weaker == old.provenance else exchange.pedigree,
                }
            )
        self.items[exchange.key] = exchange
        if component is not None:
            self.components[exchange.key] = component

    def fate(
        self, component: str, fate: str, amount: float, **values: Any
    ) -> DatasetExchange | None:
        """A component's amount sent to *fate* (not ``coproduct``)."""
        if amount <= 0:
            return None
        prefix, suffix, kind, compartment = FATES[fate]
        found = self.chemistry.components.get(component)
        cas = found.cas if found is not None and found.cas else None
        link = flow = None
        if compartment is not None:
            atoms = found.formula if found is not None else ""
            origin = self.origin if CARBON in _elements(atoms) else "fossil"
            spec = Elementary(compartment=compartment, origin=origin)
            link = Background(elementary=spec, source=f"{compartment} emission ({fate})")
            flow, _ = identities(cas, spec)
        exchange = DatasetExchange(
            key=f"{prefix}:{component}{suffix}",
            title=f"{found.name if found else component}, {_FATE_TITLES[fate]}",
            type=kind,
            amount=amount,
            unit="kg",
            cas=cas if compartment is not None else None,
            link=link,
            flow=flow or [],
            **values,
        )
        self.add(exchange, component)
        return exchange


_FATE_TITLES = {
    "air": "to air",
    "water": "to water",
    "wastewater": "to wastewater treatment",
    "waste": "to waste treatment",
}


def _elements(formula: str) -> set[str]:
    """The elements of *formula* (none when it does not read)."""
    return set(element_masses({"x": 1.0}, {"x": formula})[0])


def _wastewater_default(path: str, name: str, chemistry: Chemistry) -> Finding | None:
    """The warning that the default loss split drains *name* to wastewater treatment without an
    explicit fate: for a gas at ambient conditions (normal boiling point below 25 degC), and for
    a component whose boiling point is not given. None for a known liquid or solid."""
    found = chemistry.components.get(name)
    boiling = found.normal_boiling_point if found is not None else None
    if boiling is not None and boiling >= AMBIENT_K:
        return None
    why = (
        f"a gas at ambient conditions (normal boiling point {boiling:g} K)"
        if boiling is not None
        else "of unknown volatility (no normal_boiling_point in process/materials.yaml)"
    )
    return Finding(
        path,
        "warning",
        "cheme.lci-loss-split",
        f"the default loss split sends the unconverted {name}, {why}, to wastewater "
        "treatment without an explicit fate",
        ids=[name],
        hint=f"set losses.fate: {{{name}: air}} (or water, waste, wastewater) with a reason, or "
        "losses.water to state the rest's destination",
    )


def _floored(scores: tuple[int, ...], floor: tuple[int, ...]) -> list[int]:
    return [max(s, f) for s, f in zip(scores, floor, strict=True)]


def _build(
    spec: LciEstimate,
    chemistry: Chemistry,
    defaults: TierDefaults,
    path: str,
    findings: list[Finding] | None = None,
) -> LciDataset:
    """The dataset of *spec* (without its balance record); warnings about its defaults are
    appended to *findings*. Raises ValueError for an estimate the reactions cannot give."""
    findings = [] if findings is None else findings
    missing = [r for r in spec.reactions if r not in chemistry.reactions]
    if missing:
        raise ValueError(f"reactions not in process/reactions.yaml: {', '.join(missing)}")
    reactions = [chemistry.reactions[r] for r in spec.reactions]
    formulas = chemistry.formulas()
    floor = defaults.floors[spec.tier]
    values = defaults.values

    def default(name: str) -> dict[str, Any]:
        """The provenance, source and pedigree of an exchange taking the default *name*."""
        entry = values[name]
        built.use(name)
        status = "" if entry.status == "confirmed" else f" [{entry.status}]"
        return {
            "provenance": "assumed",
            "origin": "design-rule",
            "source": f"{defaults.rule(name)}{status}: {entry.source}",
            "pedigree": Pedigree(scores=_floored(entry.pedigree, floor), rule=defaults.rule(name)),
        }

    efficiency = spec.yield_.value if spec.yield_ is not None else values["yield"].value
    balance = stoichiometric_balance(
        reactions, formulas, spec.product, efficiency, spec.key, spec.selectivity or None
    )
    # a fate for a component the scheme does not feed or form would be ignored silently
    stray = sorted(set(spec.losses.fate) - set(balance.fed))
    if stray:
        raise ValueError(
            f"losses.fate names {', '.join(stray)}, not a reactant of {' + '.join(spec.reactions)}"
        )
    stray = sorted(set(spec.byproducts) - set(balance.formed))
    if stray:
        raise ValueError(
            f"byproducts names {', '.join(stray)}, not formed by {' + '.join(spec.reactions)}"
        )
    built = _Exchanges(chemistry, spec.origin)
    scheme = " + ".join(spec.reactions)
    # several reactions: the amounts follow from the selectivities, which are only as good as
    # their source; without one they are assumed, not calculated
    unsourced = len(spec.reactions) > 1 and spec.selectivity_source is None
    shown = (
        f"; selectivities from {spec.selectivity_source.source}"
        if spec.selectivity_source is not None
        else ""
    )
    assumed_selectivity = {
        "provenance": "assumed",
        "origin": "estimate",
    }
    product = chemistry.components.get(spec.product)
    built.add(
        DatasetExchange(
            key=f"product:{spec.product}",
            title=product.name if product else spec.product,
            type="product",
            amount=1.0,
            unit="kg",
            provenance="given",
            source="the reference flow: 1 kg of the product",
        ),
        spec.product,
    )
    # the reactants fed: the scheme's consumption at the efficiency
    for name, kg in sorted(balance.fed.items()):
        if spec.yield_ is None:
            how = default("yield")
            how["source"] = (
                f"stoichiometry of {scheme} at efficiency {efficiency:g}{shown}; {how['source']}"
            )
            if unsourced:
                how["source"] += "; the selectivities have no source (selectivity_source)"
        else:
            how = {
                "provenance": "calculated",
                "source": f"stoichiometry of {scheme} at the yield {efficiency:g} of "
                f"{spec.yield_.source}{shown}",
                "source_id": spec.yield_.source_id,
            }
            if unsourced:
                how = {
                    **how,
                    **assumed_selectivity,
                    "source": how["source"]
                    + "; assumed: the selectivities have no source (selectivity_source)",
                }
        found = chemistry.components.get(name)
        built.add(
            DatasetExchange(
                key=f"feed:{name}",
                title=found.name if found else name,
                type="input",
                amount=kg,
                unit="kg",
                **how,
            ),
            name,
        )
    # the products of the scheme besides the reference product: each needs a fate
    for name, kg in sorted(balance.formed.items()):
        if name == spec.product:
            continue
        byproduct = spec.byproducts.get(name)
        if byproduct is None:
            raise ValueError(
                f"the reactions form {name} ({kg:.4g} kg per kg): give its fate in byproducts "
                "(coproduct, air, water, wastewater, waste)"
            )
        how = {
            "provenance": "calculated",
            "source": f"stoichiometry of {scheme}{shown}"
            + (f"; {byproduct.reason}" if byproduct.reason else ""),
        }
        if unsourced:
            how = {
                **how,
                **assumed_selectivity,
                "source": how["source"]
                + "; assumed: the selectivities have no source (selectivity_source)",
            }
        if byproduct.fate == "coproduct":
            found = chemistry.components.get(name)
            built.add(
                DatasetExchange(
                    key=f"product:{name}",
                    title=found.name if found else name,
                    type="product",
                    amount=kg,
                    unit="kg",
                    properties=byproduct.properties,
                    **how,
                ),
                name,
            )
        else:
            built.fate(name, byproduct.fate, kg, **how)
    # the unconverted input: a fate per component, else the air share and the rest to water
    losses = spec.losses
    for name, kg in sorted(balance.unconverted.items()):
        if kg <= 0:
            continue
        if name in losses.fate:
            built.fate(
                name,
                losses.fate[name],
                kg,
                provenance="assumed",
                origin="estimate",
                source=f"unconverted input (efficiency {efficiency:g}): {losses.reason}",
            )
            continue
        if losses.air is not None:
            share = losses.air.value
            air = {
                "provenance": "assumed",
                "origin": "literature",
                "source": f"{share:g} of the input to air: {losses.air.source}",
                "source_id": losses.air.source_id,
            }
        else:
            share = values["loss-air"].value
            air = default("loss-air")
        if "water" not in losses.model_fields_set:
            warning = _wastewater_default(path, name, chemistry)
            if warning is not None:
                findings.append(warning)
        to_air = min(share * balance.fed[name], kg)
        built.fate(name, "air", to_air, **air)
        built.fate(name, losses.water, kg - to_air, **default("loss-water"))
        built.use("loss-waste")  # its share is 0: no exchange
    # energy: sourced, or the site averages
    for name, kind in (("electricity", "electricity"), ("heat", "heat")):
        given = getattr(spec, name)
        if given is not None:
            how = {
                "provenance": "given",
                "origin": "literature",
                "source": given.source,
                "source_id": given.source_id,
            }
            amount = given.value
        else:
            how = default(name)
            amount = values[name].value
        built.add(
            DatasetExchange(
                key=f"input:{name}",
                title=values[name].title.split(" per ")[0],
                type="input",
                amount=amount,
                unit="kWh",
                carrier=Carrier(
                    kind=values[name].carrier or kind,
                    source=values[name].carrier_note if given is None else "",
                ),
                **how,
            )
        )
    for extra in spec.exchanges:
        if extra.key in built.items:
            raise ValueError(
                f"{extra.key} is generated: give it through yield, electricity, heat, "
                "byproducts or losses"
            )
        if extra.component is not None and extra.component not in formulas:
            raise ValueError(f"{extra.key}: component {extra.component} has no formula")
        built.add(
            DatasetExchange(
                key=extra.key,
                title=extra.title,
                type=extra.type,
                amount=extra.amount,
                unit=extra.unit,
                cas=extra.cas,
                carrier=extra.carrier,
                link=extra.link,
                provenance="given",
                origin="literature",
                source=extra.source,
                source_id=extra.source_id,
            ),
            extra.component,
        )
    exchanges = list(built.items.values())
    generation = Generation(
        tier=spec.tier,
        method=METHODS[spec.tier],
        defaults=defaults.label,
        defaults_used=built.used,
        spec=path,
        maturity_cap=TIER_MATURITY_CAP[spec.tier],  # type: ignore[arg-type]
        pedigree_floor=list(floor),
        dqr_floor=dqr_floor(floor),
        components=dict(sorted(built.components.items())),
        formulas={k: formulas[c] for k, c in sorted(built.components.items()) if c in formulas},
        # a placeholder until the balance is computed from the written exchanges
        balance={"closed": False, "tolerance": 1e-6},
    )
    dataset = LciDataset.model_validate(
        {
            "schema": DATASET_SCHEMA,
            "kind": "lci_dataset",
            "id": spec.id,
            "title": spec.title
            or f"{product.name if product else spec.product} (Tier {spec.tier})",
            "description": spec.description
            or f"Screening estimate (Tier {spec.tier}) of {scheme}: not derived from a design."
            + (
                " The energy defaults are Gendorf 2000 site averages (ASSUMED, older than the "
                "10-year limit for secondary data): valid_until follows the reference year and "
                "does not endorse their age."
                if {"electricity", "heat"} & set(built.used)
                else ""
            ),
            "basis": f"1 kg of {product.name if product else spec.product}",
            "location": spec.location,
            "year": spec.year,
            "boundary": "gate-to-gate, the reaction step with its energy (screening estimate)",
            "technology": spec.technology or f"{scheme} (Tier {spec.tier} estimate)",
            "sources": [s.model_dump(by_alias=True) for s in spec.sources],
            "exchanges": [e.model_dump(by_alias=True, exclude_none=True) for e in exchanges],
            "provenance": DatasetProvenance(
                generator="cheme assess lci-estimate", notes=f"estimate {path}"
            ).model_dump(),
            "generation": generation.model_dump(by_alias=True),
        }
    )
    dataset = _document(dataset, spec)
    # what the rule gives every exchange without a pedigree, under the tier's floor
    return score(dataset)


def _document(dataset: LciDataset, spec: LciEstimate) -> LciDataset:
    """*dataset* with the estimate's documentation and what a screening estimate states."""
    given = spec.documentation or DatasetDocumentation()
    update = {k: getattr(given, k) for k in given.model_dump(exclude_unset=True)}
    update.setdefault("uuid", str(_uuid.uuid5(NAMESPACE, f"estimate/{spec.id}")))
    update.setdefault("system_model", "cutoff")
    update.setdefault("modelling", Modelling(principle="attributional"))
    update.setdefault(
        "system_boundary",
        SystemBoundary(
            included=["the reactions as balanced", "electricity and heat of the process"],
            excluded=[
                "infrastructure: no design provides it (the defaults' generic plant, 4e-10 "
                "units per kg after Hischier et al. 2005, is not applied)",
                "transport of the inputs (the standard distances of Hischier et al. 2005, 100 km "
                "lorry and 600 km train, are recorded in the defaults, not applied)",
                "cooling water and process water (not estimated: biases the inventory low)",
                "air, N2 and O2 are not inventoried as resources (ecoinvent rule); a reactant "
                "among them is an input feed:<id> that the element balance needs",
                "catalysts and auxiliaries not given as exchanges",
            ],
            cutoff="screening estimate: no cut-off criterion applied",
            infrastructure="excluded",
            catalysts="excluded",
        ),
    )
    if dataset.year is not None:
        update.setdefault("time", DatasetTime(start=dataset.year))
        update.setdefault("valid_until", dataset.year + VALID_YEARS)
    return dataset.model_copy(update=update)


def estimate_yaml(result: EstimateResult) -> str:
    """The dataset of *result* as the YAML ``--write`` writes (empty without one)."""
    from chemeascode.domains.assessment.lca.report import _DatasetDumper

    dataset = result.dataset
    if dataset is None:
        return ""
    data = dataset.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
    # every exchange states its provenance, assumed included (the default the dump leaves out)
    for entry, exchange in zip(data["exchanges"], dataset.exchanges, strict=True):
        keys = list(entry)
        at = keys.index("unit") + 1
        entry.pop("provenance", None)
        items = [*entry.items()]
        items.insert(at, ("provenance", exchange.provenance))
        entry.clear()
        entry.update(items)
    head = {
        "schema": dataset.schema_,
        "kind": dataset.kind,
        "id": dataset.id,
        "title": dataset.title,
        "description": dataset.description,
        "scope": dataset.scope,
        "basis": dataset.basis,
        "generation": data["generation"],
    }
    data = {**head, **{k: v for k, v in data.items() if k not in head}}
    header = (
        f"# A Tier {dataset.generation.tier} LCI estimate (kind lci_dataset): generated by cheme "
        f"assess lci-estimate\n# --write from {result.spec_path}; do not edit, change the "
        "estimate and regenerate. A screening\n# dataset: every exchange marked assumed takes a "
        "default rule (generation.defaults_used).\n"
    )
    return header + yaml.dump(
        data, Dumper=_DatasetDumper, sort_keys=False, allow_unicode=True, width=100
    )


# -- checks of a generated dataset --------------------------------------------------------------


def tier_findings(dataset: LciDataset, path: str, maturity: str | None = None) -> list[Finding]:
    """What a generated *dataset* (read from *path*) breaks of its tier: an element balance
    that does not close, a default exchange not marked assumed or not listed, a pedigree better
    than the tier's floor, and a manifest *maturity* (``process.yaml``) above the tier's cap.
    Plus a note that the dataset is a screening estimate. Empty for a dataset without
    ``generation``."""
    generation = dataset.generation
    if generation is None:
        return []
    found: list[Finding] = []
    if generation.tier in TIER_MATURITY_CAP:
        found.append(
            Finding(
                path,
                "info",
                "cheme.lci-tier",
                f"{dataset.id} is a Tier {generation.tier} estimate ({generation.method}): "
                "screening only, not derived from a design",
                ids=[dataset.id],
                hint="results resting on it carry its tier; replace it with a flowsheet-derived "
                "dataset (Tier 2) before a decision depends on it",
            )
        )
        balance = element_balance(dataset, tolerance=generation.balance.tolerance)
        if not balance.closed:
            found.append(_unbalanced(path, balance))
        loose = [e.key for e in dataset.exchanges if e.unit == "kg" and e.key in balance.outside]
        if loose:
            found.append(
                Finding(
                    path,
                    "warning",
                    "cheme.lci-mass-outside-balance",
                    f"{dataset.id}: mass exchanges without a component and formula are not in "
                    f"the element balance, so its closing says nothing about them: "
                    f"{', '.join(loose)}",
                    ids=[dataset.id],
                    hint="give the exchange a component with a formula, or accept that its mass "
                    "(a catalyst, an auxiliary) is not balanced",
                )
            )
    prefix = f"{generation.defaults}: " if generation.defaults else None
    for exchange in dataset.exchanges:
        rule = exchange.pedigree.rule if exchange.pedigree else ""
        if prefix and rule.startswith(prefix):
            name = rule[len(prefix) :]
            if exchange.provenance != "assumed":
                found.append(
                    _error(
                        path,
                        "cheme.lci-default-not-assumed",
                        f"{exchange.key} takes the default {name} but is {exchange.provenance}",
                        hint="an exchange taking a default is provenance: assumed",
                    )
                )
            if name not in generation.defaults_used:
                found.append(
                    _error(
                        path,
                        "cheme.lci-default-unlisted",
                        f"{exchange.key} takes the default {name}, not in generation.defaults_used",
                        hint="regenerate the dataset (cheme assess lci-estimate --write)",
                    )
                )
        floor = generation.pedigree_floor
        if floor and exchange.pedigree is not None and exchange.type != "product":
            better = [
                i
                for i, (s, f) in enumerate(zip(exchange.pedigree.scores, floor, strict=True))
                if s < f
            ]
            if better:
                found.append(
                    _error(
                        path,
                        "cheme.lci-tier-quality",
                        f"{exchange.key}: pedigree {exchange.pedigree.scores} is better than the "
                        f"Tier {generation.tier} floor {floor}",
                        hint="a tier caps the data quality; a better pedigree needs a higher "
                        "tier (sourced data, then a flowsheet)",
                    )
                )
    cap = TIER_LIBRARY_CAP.get(generation.tier)
    if (
        cap is not None
        and maturity in LIBRARY_MATURITY
        and LIBRARY_MATURITY.index(maturity) > LIBRARY_MATURITY.index(cap)
    ):
        found.append(
            _error(
                "process.yaml",
                "cheme.lci-tier-maturity",
                f"design maturity {maturity} is above what the Tier {generation.tier} dataset "
                f"{dataset.id} supports ({cap}: calculation maturity "
                f"{generation.maturity_cap or TIER_MATURITY_CAP[generation.tier]})",
                hint="lower the manifest's design maturity, or derive the dataset from a balanced "
                "flowsheet (Tier 2)",
            )
        )
    return found


# -- validation against a full design -----------------------------------------------------------


@dataclass
class Deviation:
    """One quantity of an estimate against the design's: per kg of the reference product."""

    quantity: str
    estimate: float
    design: float
    unit: str = "kg"

    @property
    def error(self) -> float | None:
        """(estimate - design) / design; None when the design has none."""
        return (self.estimate - self.design) / self.design if self.design else None


@dataclass
class Comparison:
    """An estimate against a flowsheet: the deviations and what could not be compared."""

    product: str
    case: str
    deviations: list[Deviation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def error_range(self) -> tuple[float, float] | None:
        errors = [d.error for d in self.deviations if d.error is not None]
        return (min(errors), max(errors)) if errors else None


ELECTRICITY_WORDS = ("electricity", "electric", "power")
HEAT_WORDS = ("heat", "steam", "fired", "fuel", "hot_oil", "hot oil")
#: Words of a terminal that remove or reject energy: never a supply, whatever else they say.
REMOVAL_WORDS = ("cool", "reject", "refriger", "condens", "chill", "quench", "removal")


def design_energy(terminals_: list, made: float) -> tuple[dict[str, float], dict[str, float]]:
    """The energy terminals of a design per kg of product (*made* kg/h): the electricity and heat
    supplied to it (``input:electricity``, ``input:heat``, kWh/kg), and the other terminals
    (outputs, cooling or heat rejection, generated or exported energy, unnamed carriers) that are
    not compared. A terminal counts as a supply only when it is an input and names electricity or
    heat (steam, fired heat, fuel) without naming a removal."""
    supplied = {"input:electricity": 0.0, "input:heat": 0.0}
    other: dict[str, float] = {}
    for terminal in terminals_:
        text = f"{terminal.key} {terminal.title}".lower()
        per_kg = terminal.per_hour / made
        key = None
        if terminal.direction == "input" and not any(w in text for w in REMOVAL_WORDS):
            if any(w in text for w in ELECTRICITY_WORDS):
                key = "input:electricity"
            elif any(w in text for w in HEAT_WORDS):
                key = "input:heat"
        if key is None:
            other[terminal.key] = other.get(terminal.key, 0.0) + per_kg
        else:
            supplied[key] += per_kg
    return supplied, other


def compare_with_design(dataset: LciDataset, root: Path, case: str | None = None) -> Comparison:
    """*dataset* (a generated estimate) against the flowsheet of the repository at *root* in
    *case* (default: the flowsheet's default case), per kg of the reference product: each
    reactant fed, the unconverted input that leaves (by component, summed over its fates), and
    the energy where the design has energy terminals. Raises ValueError when the flowsheet does
    not load or does not make the product."""
    from chemeascode.domains.assessment.flows import terminals
    from chemeascode.domains.process.model import load

    if dataset.generation is None:
        raise ValueError(f"{dataset.id} is not a generated estimate")
    process, _ = load(Path(root))
    if process is None:
        raise ValueError("no loadable process/flowsheet.yaml")
    fs = process.flowsheet
    case = case or next((c.id for c in fs.cases if c.default), fs.cases[0].id)
    reference = next(e for e in dataset.products())
    component = dataset.generation.components.get(reference.key, reference.key.split(":", 1)[1])
    ends = terminals(process, case)
    feeds = [t for t in ends if t.direction == "input" and t.kind == "material"]
    products = [t for t in ends if t.direction == "output" and t.kind == "material"]
    main = max(products, key=lambda t: t.components.get(component, 0.0), default=None)
    made = main.components.get(component, 0.0) if main is not None else 0.0
    if made <= 0:
        raise ValueError(f"the flowsheet makes no {component} in case {case}")
    comparison = Comparison(product=component, case=case)
    components = dataset.generation.components
    by_component: dict[str, dict[str, float]] = {"feed": {}, "loss": {}}
    for exchange in dataset.exchanges:
        name = components.get(exchange.key)
        if name is None or exchange.type == "product":
            continue
        side = "feed" if exchange.key.startswith("feed:") else "loss"
        by_component[side][name] = by_component[side].get(name, 0.0) + exchange.amount
    design_feed: dict[str, float] = {}
    for terminal in feeds:
        for name, kg in terminal.components.items():
            design_feed[name] = design_feed.get(name, 0.0) + kg / made
    design_out: dict[str, float] = {}
    for terminal in products:
        if terminal is main:
            continue
        for name, kg in terminal.components.items():
            design_out[name] = design_out.get(name, 0.0) + kg / made
    for name, kg in sorted(by_component["feed"].items()):
        comparison.deviations.append(Deviation(f"feed:{name}", kg, design_feed.get(name, 0.0)))
        loss = by_component["loss"].get(name, 0.0)
        comparison.deviations.append(Deviation(f"loss:{name}", loss, design_out.get(name, 0.0)))
    inert = sorted(set(design_feed) - set(by_component["feed"]) - {component})
    if inert:
        comparison.notes.append(
            "fed in the design but not in the reactions (inerts, not estimated): "
            + ", ".join(inert)
        )
    energy = [t for t in ends if t.kind == "energy"]
    if not energy:
        comparison.notes.append(
            "the design has no energy terminals: electricity and heat not compared"
        )
    else:
        supplied, other = design_energy(energy, made)
        for key, total in supplied.items():
            estimate = next((e.amount for e in dataset.exchanges if e.key == key), None)
            if estimate is not None and total:
                comparison.deviations.append(Deviation(key, estimate, total, "kWh"))
        comparison.notes.append(
            "energy supplied to the design: "
            + (
                ", ".join(f"{k.split(':')[1]} {v:.4g} kWh/kg" for k, v in supplied.items())
                or "none"
            )
        )
        if other:
            comparison.notes.append(
                "energy terminals not compared (not an electricity or heat supply): "
                + ", ".join(f"{k} {v:.4g} kWh/kg" for k, v in other.items())
            )
    return comparison
