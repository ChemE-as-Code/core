"""Impacts per functional unit: the inventory's mapped rows times their background.

Two backends give the same :class:`Impact` lines:

- :func:`characterise` (``backend: factors``): each row mapped ``factor: <id>`` times that
  factor's value in each category of ``lca/factors.yaml``: ``quantity x value / unit``, the
  factor's unit converted to the row's (``FACTOR_UNITS``). No licensed data needed.
- :func:`characterise_brightway` (``backend: brightway``): each row mapped to an ``activity``
  times that activity's cradle-to-gate score per unit in each method, and each row mapped to a
  ``biosphere`` flow times the method's factor for it, from the Brightway project
  (``integrations.brightway``).

A scenario replaces factor ids (factors) or database names (Brightway) before the lookup.
Rows mapped ``free`` and co-products carry nothing. What cannot be characterised is never
counted as 0 silently: each exchange and category without a burden is a :class:`Gap` (an
unmapped flow, a factor without that category, an emission the method does not characterise,
an unlinked exchange of a referenced dataset), kept with its quantity and reported beside the
totals, which exclude it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.assessment.lca.allocation import MISSING
from chemeascode.domains.assessment.lca.elementary import BIOSPHERE3_CATEGORIES
from chemeascode.domains.assessment.lca.inventory import Inventory, InventoryRow
from chemeascode.domains.assessment.lca.methods import categories as packaged
from chemeascode.domains.assessment.lca.methods import factor as method_factor
from chemeascode.domains.assessment.lca.methods import listed as method_listed
from chemeascode.domains.assessment.lca.schemas import (
    FACTOR_UNITS,
    INVENTORY_UNITS,
    Brightway,
    Category,
    FactorFile,
)
from chemeascode.foundation.findings import Finding

FACTORS_FILE = "lca/factors.yaml"
#: ``elementary: none`` on a category: the plant's direct emissions do not contribute to it
#: (declared), so they are no gap there.
NO_ELEMENTARY = "none"
LCA_FILE = "lca/lca.yaml"
_KIND = {unit: kind for kind, unit in INVENTORY_UNITS.items()}


@dataclass(frozen=True)
class Impact:
    """One contribution: an inventory row's impact in one category, per functional unit."""

    category: str
    key: str
    #: What the row is characterised with: a factor id, or a Brightway activity or flow.
    basis: str
    quantity: float
    unit: str
    #: Impact per unit of the row (kg, kWh, m, ...).
    factor: float
    value: float
    status: str = ""
    source: str = ""
    year: int | None = None
    #: ``baseline`` or a scenario id.
    scenario: str = "baseline"
    #: ``operation`` or ``construction``.
    phase: str = "operation"
    #: The source registry entry of the factor (``sources:``), and the geography it represents.
    source_id: str = ""
    location: str = ""


#: Why an exchange carries no burden in a category (:class:`Gap`).
GAP_REASONS = {
    "unmapped": "no background in lca/lca.yaml",
    "no-weight": "an equipment item of the construction has no weight: amount unknown",
    "unmatched": "no construction entry counts this take-off row or item: amount unknown",
    "no-takeoff": "the construction entry's take-off or equipment list is absent: amount unknown",
    "missing": "declared missing: no background available",
    "factor-category": "its factor has no value in this category",
    "elementary-unlinked": "the category names no packaged method for direct emissions",
    "elementary-uncharacterised": "outside the method: it has no factor for this emission",
    "elementary-origin": "the method characterises this substance, but has no factor for its "
    "origin (e.g. methane from land-use change)",
    "biosphere-uncharacterised": "outside the method: the Brightway method does not "
    "characterise this flow",
    "dataset-category": "the referenced dataset has no score in this category",
    "dataset-unlinked": "an exchange of the referenced dataset has no background",
}


#: Reasons that are not gaps: an elementary flow a method does not list contributes nothing to
#: that category by the method's definition (an LCIA convention). They are reported beside the
#: gaps, but leave the totals complete.
OUTSIDE_METHOD = ("elementary-uncharacterised", "biosphere-uncharacterised")


@dataclass(frozen=True)
class Gap:
    """An exchange whose burden in *category* is unknown: excluded from the totals, never 0."""

    category: str
    key: str
    reason: str
    #: Per functional unit; None when the amount itself is unknown (no-weight, unmatched).
    quantity: float | None
    unit: str
    phase: str = "operation"
    scenario: str = "baseline"
    detail: str = ""


def real_gaps(gaps: list[Gap]) -> list[Gap]:
    """The gaps that leave a burden unknown (not those outside a method's scope)."""
    return [g for g in gaps if g.reason not in OUTSIDE_METHOD]


@dataclass
class UnitScore:
    """What one unit of a dataset's product carries: its unit and the impact per category."""

    unit: str
    values: dict[str, float]
    #: e.g. ``dataset:lca/datasets/h2.yaml#H2 (mass)``.
    label: str
    #: What the score lacks, per unit of the product (keys ``<path>#<exchange>``).
    gaps: list[Gap] = field(default_factory=list)
    #: The source ids its impacts come from, and the statuses, geographies and reference years
    #: of its contributions (with the dataset's own), so the study can judge them.
    sources: set[str] = field(default_factory=set)
    statuses: set[str] = field(default_factory=set)
    locations: set[str] = field(default_factory=set)
    years: set[int] = field(default_factory=set)


#: Resolves a dataset background (:class:`~.schemas.DatasetRef`) in a scenario (its
#: replacements) to its :class:`UnitScore`, or the problem as text.
DatasetScores = Callable[[Any, str, dict[str, str]], "UnitScore | str"]


def _dataset_impacts(
    row: InventoryRow,
    background: Any,
    category_ids: list[str],
    datasets: DatasetScores | None,
    scenario: str,
    replace: dict[str, str],
    gaps: list[Gap],
) -> tuple[list[Impact], str]:
    """The impacts of a row whose background is a dataset (its gaps into *gaps*), or the
    problem."""
    if datasets is None:
        return [], "datasets cannot be resolved here"
    score = datasets(background.dataset, scenario, replace)
    if isinstance(score, str):
        return [], score
    if _KIND.get(score.unit) != _KIND.get(row.unit):
        return [], f"{row.key} is counted in {row.unit}, {score.label} is per {score.unit}"
    for gap in score.gaps:
        gaps.append(
            Gap(
                gap.category,
                f"{row.key} < {gap.key}",
                gap.reason,
                None if gap.quantity is None else row.quantity * gap.quantity,
                gap.unit,
                row.phase,
                scenario,
                gap.detail,
            )
        )
    impacts = []
    for category in category_ids:
        if category not in score.values:
            gaps.append(
                Gap(
                    category,
                    row.key,
                    "dataset-category",
                    row.quantity,
                    row.unit,
                    row.phase,
                    scenario,
                    score.label,
                )
            )
            continue
        impacts.append(
            Impact(
                category,
                row.key,
                score.label,
                row.quantity,
                row.unit,
                score.values[category],
                row.quantity * score.values[category],
                ",".join(sorted(score.statuses | ({"PROXY"} if background.proxy else set()))),
                background.source,
                # the oldest reference year: the one a study's year check must see
                min(score.years) if score.years else None,
                scenario,
                row.phase,
                ",".join(sorted(score.sources)),
                ",".join(sorted(score.locations)),
            )
        )
    return impacts, ""


def _rows(inventory: Inventory) -> list[InventoryRow]:
    return [row for row in inventory.rows if row.key in inventory.backgrounds]


def unmapped_gaps(inventory: Inventory, categories: list[str], scenario: str) -> list[Gap]:
    """A gap per category for every exchange of *inventory* without a background (not free, not
    a co-product, not released as its emissions)."""
    found = []
    for row in inventory.rows:
        if row.key in inventory.backgrounds:
            continue
        if row.mapping.startswith(MISSING):
            reason, detail = "missing", row.mapping.removeprefix(MISSING)
        elif not row.mapping:
            reason, detail = "unmapped", ""
        else:
            continue
        found += [
            Gap(category, row.key, reason, row.quantity, row.unit, row.phase, scenario, detail)
            for category in categories
        ]
    found += [
        Gap(category, key, reason, None, "", "construction", scenario, detail)
        for key, reason, detail in inventory.unknown
        for category in categories
    ]
    return found


def _units_of(kind: str | None) -> str:
    return ", ".join(u for u, (k, _) in FACTOR_UNITS.items() if k == kind)


def characterise(
    inventory: Inventory,
    factors: FactorFile,
    categories: list[str],
    replace: dict[str, str] | None = None,
    scenario: str = "baseline",
    datasets: DatasetScores | None = None,
    gaps: list[Gap] | None = None,
) -> tuple[list[Category], list[Impact], list[Finding]]:
    """The impacts of *inventory* in *categories* (all of *factors* when empty), with the
    factor ids of *replace* swapped (a scenario); a row whose background is a dataset through
    *datasets*. What cannot be characterised is added to *gaps*."""
    replace = replace or {}
    gaps = gaps if gaps is not None else []
    findings: list[Finding] = []

    def error(file: str, rule: str, message: str, hint: str, ids=()) -> None:
        findings.append(Finding(file, "error", rule, message, ids=list(ids), hint=hint))

    known = {c.id: c for c in factors.categories}
    unknown = [c for c in categories if c not in known]
    if unknown:
        error(
            LCA_FILE,
            "cheme.lca-category",
            f"categories not in {FACTORS_FILE}: {', '.join(unknown)}",
            f"use category ids of {FACTORS_FILE}: {', '.join(known)}",
            unknown,
        )
    chosen = [known[c] for c in categories if c in known] if categories else factors.categories
    by_id = {f.id: f for f in factors.factors}
    stray = sorted((set(replace) | set(replace.values())) - set(by_id))
    if stray:
        error(
            LCA_FILE,
            "cheme.lca-factor-unknown",
            f"scenario {scenario}: factors not in {FACTORS_FILE}: {', '.join(stray)}",
            f"add them to {FACTORS_FILE}, or correct the scenario's factors:",
            stray,
        )
    impacts: list[Impact] = []
    lacking: dict[str, set[str]] = {}
    unknown_methods = sorted(
        {
            c.elementary
            for c in chosen
            if c.elementary and c.elementary != NO_ELEMENTARY and c.elementary not in packaged()
        }
    )
    if unknown_methods:
        error(
            FACTORS_FILE,
            "cheme.lca-elementary",
            f"categories name unknown packaged methods: {', '.join(unknown_methods)}",
            f"use one of {', '.join(packaged())}",
            unknown_methods,
        )
    for row in _rows(inventory):
        background = inventory.backgrounds[row.key]
        if background.elementary is not None and not row.cas:
            error(
                LCA_FILE,
                "cheme.lca-elementary",
                f"{row.key} is elementary but its component has no CAS number",
                "give the component its cas in process/materials.yaml",
                [row.key],
            )
            continue
        if background.elementary is not None:
            e = background.elementary
            linked = [c for c in chosen if c.elementary in packaged()]
            if not linked and all(c.elementary == NO_ELEMENTARY for c in chosen):
                continue  # declared: direct emissions contribute to none of the categories
            if not linked:
                error(
                    LCA_FILE,
                    "cheme.lca-elementary",
                    f"{row.key} is elementary, but no category of {FACTORS_FILE} names a "
                    "packaged method (elementary:)",
                    "give the category elementary: ipcc2021-gwp100 (for example), or map the "
                    "emission to a factor",
                    [row.key],
                )
                continue
            if row.unit != "kg":
                error(LCA_FILE, "cheme.lca-elementary", f"{row.key} is not in kg", "", [row.key])
                continue
            characterised = False
            for category in linked:
                value = method_factor(category.elementary, row.cas, e.compartment, e.origin)
                if value is None:
                    known = method_listed(category.elementary, row.cas, e.compartment)
                    gaps.append(
                        Gap(
                            category.id,
                            row.key,
                            "elementary-origin" if known else "elementary-uncharacterised",
                            row.quantity,
                            row.unit,
                            row.phase,
                            scenario,
                            f"{category.elementary}: CAS {row.cas}, {e.compartment}, {e.origin}",
                        )
                    )
                    continue
                characterised = True
                impacts.append(
                    Impact(
                        category.id,
                        row.key,
                        f"{category.elementary} ({row.cas}, {e.compartment}, {e.origin})",
                        row.quantity,
                        row.unit,
                        value,
                        row.quantity * value,
                        "PUBLISHED",
                        packaged()[category.elementary]["source"],
                        None,
                        scenario,
                        row.phase,
                        f"method:{category.elementary.partition('-')[0]}",
                    )
                )
            unlinked = [
                c.id
                for c in chosen
                if c.elementary not in packaged() and c.elementary != NO_ELEMENTARY
            ]
            gaps += [
                Gap(c, row.key, "elementary-unlinked", row.quantity, row.unit, row.phase, scenario)
                for c in unlinked
            ]
            if unlinked:
                findings.append(
                    Finding(
                        FACTORS_FILE,
                        "warning",
                        "cheme.lca-elementary-unlinked",
                        f"{row.key} is a gap in {', '.join(unlinked)}: these categories name no "
                        "packaged method (elementary:)",
                        ids=[row.key],
                        hint="link a packaged method, or state elementary: none when direct "
                        "emissions do not contribute to the category",
                    )
                )
            if not characterised:
                findings.append(
                    Finding(
                        LCA_FILE,
                        "warning",
                        "cheme.lca-elementary-uncharacterised",
                        f"{row.key} (CAS {row.cas or 'unknown'}, {e.compartment}, {e.origin}) "
                        "has no factor in "
                        + ", ".join(sorted({c.elementary for c in linked}))
                        + ": a gap, not in the totals",
                        ids=[row.key],
                        hint="map it free when it has no effect in these categories, or to a "
                        "factor",
                    )
                )
            continue
        if background.dataset is not None:
            found, problem = _dataset_impacts(
                row, background, [c.id for c in chosen], datasets, scenario, replace, gaps
            )
            impacts += found
            if problem:
                error(
                    LCA_FILE,
                    "cheme.lca-dataset",
                    problem,
                    "check the dataset: entry",
                    [row.key],
                )
            continue
        if background.factor is None:
            error(
                LCA_FILE,
                "cheme.lca-factor-unknown",
                f"{row.key} has no factor: (backend factors)",
                f"give it a factor of {FACTORS_FILE}, or use backend: brightway",
                [row.key],
            )
            continue
        factor_id = replace.get(background.factor, background.factor)
        factor = by_id.get(factor_id)
        if factor is None:
            error(
                LCA_FILE,
                "cheme.lca-factor-unknown",
                f"{row.key} maps to factor {factor_id!r}, which {FACTORS_FILE} lacks",
                f"add factor {factor_id} to {FACTORS_FILE} or map the flow to one it has",
                [row.key],
            )
            continue
        kind, per = FACTOR_UNITS[factor.unit]
        if kind != _KIND.get(row.unit):
            error(
                FACTORS_FILE,
                "cheme.lca-factor-unit",
                f"factor {factor.id} is per {factor.unit} ({kind}); {row.key} is counted in "
                f"{row.unit}",
                f"give {row.key} a factor per {_units_of(_KIND.get(row.unit))}",
                [factor.id, row.key],
            )
            continue
        for category in chosen:
            if category.id not in factor.values:
                lacking.setdefault(factor.id, set()).add(category.id)
                gaps.append(
                    Gap(
                        category.id,
                        row.key,
                        "factor-category",
                        row.quantity,
                        row.unit,
                        row.phase,
                        scenario,
                        factor.id,
                    )
                )
                continue
            value = factor.values[category.id] / per
            impacts.append(
                Impact(
                    category.id,
                    row.key,
                    factor.id,
                    row.quantity,
                    row.unit,
                    value,
                    row.quantity * value,
                    "PROXY" if background.proxy else factor.status,
                    factor.source,
                    factor.year,
                    scenario,
                    row.phase,
                    factor.source_id or "",
                    factor.location,
                )
            )
    for factor_id, missing in lacking.items():
        findings.append(
            Finding(
                FACTORS_FILE,
                "warning",
                "cheme.lca-factor-category",
                f"factor {factor_id} has no value for {', '.join(sorted(missing))}: a gap, not in "
                "the totals",
                ids=[factor_id],
                hint="add the value (0 when the flow truly has none) with its source",
            )
        )
    return list(chosen), impacts, findings


def _biosphere3_uuid(cas: str | None, spec: Any) -> str | None:
    """The biosphere3 UUID of the elementary flow *spec* maps (the packaged crosswalk), or None
    when the crosswalk does not hold it."""
    from chemeascode.domains.assessment.lca.elementary import identities

    found, _ = identities(cas, spec)
    return next((f.uuid for f in found if f.list == "biosphere3"), None)


def characterise_brightway(
    inventory: Inventory,
    brightway: Brightway,
    replace: dict[str, str] | None = None,
    scenario: str = "baseline",
    datasets: DatasetScores | None = None,
    gaps: list[Gap] | None = None,
) -> tuple[list[Category], list[Impact], list[Finding]]:
    """The impacts of *inventory* with the activities and methods of the Brightway project,
    with the database names of *replace* swapped (a scenario, e.g. premise databases); a row
    whose background is a dataset through *datasets*. What the method does not characterise is
    added to *gaps*."""
    from chemeascode.integrations import brightway as bw

    replace = replace or {}
    gaps = gaps if gaps is not None else []
    method_ids = {tuple(c.method): c.id for c in brightway.categories}
    findings: list[Finding] = []
    label = "" if scenario == "baseline" else f" (scenario {scenario})"

    def error(rule: str, message: str, hint: str, ids=()) -> None:
        findings.append(Finding(LCA_FILE, "error", rule, message + label, ids=list(ids), hint=hint))

    rows = _rows(inventory)
    activities: dict[int, bw.ActivityRef] = {}
    flows: dict[int, bw.FlowRef] = {}
    linked: list[InventoryRow] = []
    for index, row in enumerate(rows):
        background = inventory.backgrounds[row.key]
        if background.dataset is not None:
            linked.append(row)
        elif background.elementary is not None:
            if not row.cas:
                error(
                    "cheme.lca-elementary",
                    f"{row.key} is elementary but its component has no CAS number",
                    "give the component its cas in process/materials.yaml",
                    [row.key],
                )
                continue
            if not brightway.biosphere:
                error(
                    "cheme.lca-elementary",
                    f"{row.key} is elementary: brightway.biosphere names no biosphere database",
                    "give brightway.biosphere (e.g. ecoinvent-3.10-biosphere)",
                    [row.key],
                )
                continue
            e = background.elementary
            # the compartment (a resource: natural resource), and the sub-compartment preferred
            compartment = "natural resource" if e.compartment == "resource" else e.compartment
            flows[index] = bw.FlowRef(
                replace.get(brightway.biosphere, brightway.biosphere),
                row.key,
                BIOSPHERE3_CATEGORIES.get((e.compartment, e.subcompartment), (compartment,)),
                cas=row.cas,
                origin=e.origin,
                uuid=_biosphere3_uuid(row.cas, e),
            )
        elif background.activity is not None:
            a = background.activity
            activities[index] = bw.ActivityRef(
                replace.get(a.database, a.database), a.name, a.reference_product, a.location
            )
        elif background.biosphere is not None:
            f = background.biosphere
            flows[index] = bw.FlowRef(
                replace.get(f.database, f.database), f.name, tuple(f.categories)
            )
        else:
            error(
                "cheme.lca-activity-missing",
                f"{row.key} has no activity: or biosphere: (backend brightway)",
                "map it to an activity of the Brightway project (cheme assess lca-search)",
                [row.key],
            )
    methods = [tuple(c.method) for c in brightway.categories]
    try:
        scores = bw.unit_scores(brightway.project, methods, activities, flows)
    except bw.BrightwayUnavailable as failure:
        error("cheme.lca-brightway", str(failure), "or use backend: factors")
        return [], [], findings
    for message in scores.errors:
        error(
            "cheme.lca-brightway",
            message,
            "import the database or method into the project (bw2io), or correct lca/lca.yaml",
        )
    if scores.errors:
        return [], [], findings
    categories = [
        Category(
            id=c.id,
            title=c.title,
            unit=scores.method_units.get(tuple(c.method)) or "-",
            method=" | ".join(c.method),
        )
        for c in brightway.categories
    ]
    impacts: list[Impact] = []
    for index, row in enumerate(rows):
        background = inventory.backgrounds[row.key]
        if index in scores.uncharacterised:
            names = ", ".join(" | ".join(m) for m in scores.uncharacterised[index])
            gaps += [
                Gap(
                    method_ids.get(tuple(m), " | ".join(m)),
                    row.key,
                    "biosphere-uncharacterised",
                    row.quantity,
                    row.unit,
                    row.phase,
                    scenario,
                    scores.labels.get(index, ""),
                )
                for m in scores.uncharacterised[index]
            ]
            findings.append(
                Finding(
                    LCA_FILE,
                    "warning",
                    "cheme.lca-biosphere-uncharacterised",
                    f"{row.key}: no characterisation factor in {names}: a gap, not in the totals"
                    + label,
                    ids=[row.key],
                    hint="check the flow's name and categories against the method, or accept "
                    "that the method does not characterise it",
                )
            )
        if index in scores.problems:
            error(
                "cheme.lca-activity-missing",
                f"{row.key}: {scores.problems[index]}",
                "correct its activity: or biosphere: (cheme assess lca-search finds them)",
                [row.key],
            )
            continue
        if index not in scores.found:
            continue
        unit, values = scores.found[index]
        kind, per = bw.UNITS.get(unit, (None, 1.0))
        if kind is None or kind != _KIND.get(row.unit):
            error(
                "cheme.lca-activity-unit",
                f"{row.key} is counted in {row.unit}, its Brightway background is per {unit!r}",
                "map it to an activity whose reference product is in the same kind of unit",
                [row.key],
            )
            continue
        missing = {tuple(m) for m in scores.uncharacterised.get(index, [])}
        ref = activities.get(index) or flows.get(index)
        database = ref.database if ref is not None else ""
        for category in brightway.categories:
            if tuple(category.method) in missing:
                continue
            value = values[tuple(category.method)] / per
            impacts.append(
                Impact(
                    category.id,
                    row.key,
                    scores.labels.get(index, ""),
                    row.quantity,
                    row.unit,
                    value,
                    row.quantity * value,
                    "PROXY" if background.proxy else "",
                    f"Brightway project {brightway.project}",
                    None,
                    scenario,
                    row.phase,
                    f"brightway:{brightway.project}/{database}",
                    (background.activity.location or "") if background.activity else "",
                )
            )
    for row in linked:
        background = inventory.backgrounds[row.key]
        found, problem = _dataset_impacts(
            row,
            background,
            [c.id for c in brightway.categories],
            datasets,
            scenario,
            replace,
            gaps,
        )
        impacts += found
        if problem:
            error("cheme.lca-dataset", problem, "check the dataset: entry", [row.key])
    return categories, impacts, findings
