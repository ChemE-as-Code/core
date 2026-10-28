"""The documentation of an LCI dataset (pre-release issue 179): what ``cheme assess lca`` fills in,
and the publication minimum the gate ``lci-documented`` requires.

:func:`document` completes the header of the plant's derived dataset from what the study
declares (``dataset:`` of ``lca/lca.yaml``) and what can be derived: a uuid stable across
versions (from the plant and the dataset id, unless the study pins one), the time period and
``valid_until`` from the reference year, the production volume from the reference product's
flow and the operating hours, and the multi-functionality from the allocation.

:data:`PUBLICATION_MINIMUM` is roughly the ILCD "data entry level": identity, geography, time,
technology, boundary, classification, modelling, review and the data generator. Every field and
its ILCD / EcoSpold2 counterpart is listed in docs/framework/lca.md. :func:`missing` names what
a dataset lacks of it, :func:`findings` reports that (and a v1 dataset's migration).
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Callable

from chemeascode.domains.assessment.lca.schemas import (
    DatasetDocumentation,
    DatasetTime,
    LcaFile,
    LciDataset,
    Modelling,
    ProductionVolume,
)
from chemeascode.foundation.findings import Finding

#: The namespace of the uuids cheme derives for datasets (uuid5 of ``<plant>/<dataset id>``):
#: the same plant and dataset id give the same uuid in every version.
NAMESPACE = _uuid.uuid5(_uuid.NAMESPACE_URL, "https://github.com/ChemE-as-Code/core/lci_dataset")
#: How many years a dataset stays valid after its reference year when the study does not say:
#: the data-freshness rule for primary data (docs/framework/lca.md, LCI datasets).
VALID_YEARS = 5


def _given(text: object) -> bool:
    return bool(text)


#: (field, test, hint): the fields a published dataset must give.
PUBLICATION_MINIMUM: tuple[tuple[str, Callable[[LciDataset], bool], str], ...] = (
    ("uuid", lambda d: _given(d.uuid), "pin it in lca/lca.yaml"),
    ("version", lambda d: _given(d.version), "major.minor.patch"),
    ("title", lambda d: _given(d.title), "the flowsheet's title"),
    ("location", lambda d: _given(d.location), "an ISO 3166-1 code, GLO, RER or RoW"),
    ("geography.description", lambda d: bool(d.geography and d.geography.description), ""),
    ("year", lambda d: d.year is not None, "the data's reference year"),
    ("valid_until", lambda d: d.valid_until is not None, "the last year of use"),
    ("system_model", lambda d: d.system_model is not None, "cutoff, apos, substitution, ..."),
    ("technology", lambda d: _given(d.technology), "the process steps"),
    ("technology_level", lambda d: d.technology_level is not None, "new ... outdated"),
    ("boundary", lambda d: _given(d.boundary) or d.system_boundary is not None, ""),
    ("classification.isic", lambda d: bool(d.classification and d.classification.isic), ""),
    ("classification.cpc", lambda d: bool(d.classification and d.classification.cpc), ""),
    (
        "modelling.principle",
        lambda d: bool(d.modelling and d.modelling.principle),
        "attributional or consequential",
    ),
    (
        "modelling.multifunctionality",
        lambda d: bool(d.modelling and d.modelling.multifunctionality) or len(d.products()) == 1,
        "how the co-products are handled",
    ),
    ("review", lambda d: bool(d.review), "unreviewed (or {type: none}) states that none was made"),
    (
        "flow identities",
        lambda d: all(
            any(f.uuid for f in e.flow) for e in d.exchanges if e.type in ("emission", "resource")
        ),
        "every emission and resource identified in a reference list (pre-release issue 175)",
    ),
    ("rights", lambda d: _given(d.rights), "the terms of its own data"),
    ("data_generator", lambda d: _given(d.data_generator), "who modelled the data"),
)


def missing(dataset: LciDataset) -> list[str]:
    """The fields of :data:`PUBLICATION_MINIMUM` *dataset* lacks."""
    return [name for name, test, _ in PUBLICATION_MINIMUM if not test(dataset)]


def findings(dataset: LciDataset, path: str) -> list[Finding]:
    """What *dataset* (read from *path*) lacks for publication (info), and whether it is a v1
    dataset read with v2's defaults (warning: ``cheme migrate --write`` or a rewrite)."""
    found = []
    if dataset.version_of_schema == "v1":
        found.append(
            Finding(
                path,
                "warning",
                "cheme.lca-dataset-v1",
                f"{path} is a v1 dataset (schema: cheme/lca/v1): read with the defaults of "
                "cheme/lci_dataset/v2 (no documentation, pedigree from the defaults rule, "
                "no flow identities)",
                hint="cheme migrate --write rewrites its schema: line (a hand-written dataset); "
                "cheme assess lca --write rewrites a generated one",
            )
        )
    gaps = missing(dataset)
    if gaps:
        hints = {name: hint for name, _, hint in PUBLICATION_MINIMUM}
        found.append(
            Finding(
                path,
                "info",
                "cheme.lca-dataset-undocumented",
                f"{dataset.id} lacks the publication minimum: {', '.join(gaps)}",
                ids=gaps,
                hint="give them in dataset: of lca/lca.yaml (or in the dataset); "
                + "; ".join(f"{n}: {hints[n]}" for n in gaps if hints[n])[:400],
            )
        )
    return found


def document(
    dataset: LciDataset, scope: LcaFile, plant: str, reference: str | None
) -> tuple[LciDataset, list[str]]:
    """*dataset* (derived from the plant named *plant*) with the documentation of *scope* and
    what can be derived; *reference* is its reference product's key. Returns the dataset and
    what was derived (for the hint of a finding)."""
    given = scope.dataset or DatasetDocumentation()
    update = given.model_dump(exclude_unset=True)
    update = {k: getattr(given, k) for k in update}
    derived: list[str] = []
    if given.uuid is None:
        update["uuid"] = str(_uuid.uuid5(NAMESPACE, f"{plant}/{dataset.id}"))
        derived.append("uuid")
    if dataset.year is not None:
        time = given.time or DatasetTime()
        if time.start is None:
            update["time"] = time.model_copy(update={"start": dataset.year})
            derived.append("time.start")
        if given.valid_until is None:
            update["valid_until"] = max(dataset.year, time.start or 0) + VALID_YEARS
            derived.append("valid_until")
    product = dataset.product(reference) if reference else None
    if given.production_volume is None and product is not None and scope.operation is not None:
        hours = scope.operation.hours_per_year
        update["production_volume"] = ProductionVolume(
            amount=product.amount * hours,
            unit=f"{product.unit}/a",
            source=f"{product.key} per hour x operation.hours_per_year ({hours:g} h/a)",
        )
        derived.append("production_volume")
    modelling = given.modelling or Modelling()
    if not modelling.multifunctionality and len(dataset.products()) > 1:
        allocation = dataset.allocation
        method = allocation.method if allocation else "mass"
        why = f": {allocation.source}" if allocation and allocation.source else ""
        update["modelling"] = modelling.model_copy(
            update={
                "multifunctionality": f"unallocated multi-output dataset; default allocation "
                f"{method}{why}"
            }
        )
        derived.append("modelling.multifunctionality")
    return dataset.model_copy(update=update), derived
