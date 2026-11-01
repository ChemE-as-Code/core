"""``cheme assess lca``: the LCA of the plant, per functional unit.

:func:`lca_report` is the Python entry point: an explicit repository root in, an
:class:`LcaReport` out (the foreground inventory, the impacts by scenario, category, phase and
contributor, the findings and the source revision of the input files). It reads
``process/flowsheet.yaml`` (through ``process``), ``lca/lca.yaml``, ``lca/factors.yaml``
(backend factors), ``estimate/mto.csv`` and ``equipment/equipment-list.yaml`` (construction)
and, with backend brightway, the Brightway project; it writes nothing.

:func:`inventory_csv`, :func:`results_csv` and :func:`results_markdown` give the generated files
``lca/inventory.csv``, ``lca/results.csv`` and ``lca/results.md``; :func:`outputs` every file
``--write`` writes.

The report also says how far the result can be read (:func:`classify`): ``complete`` within the
declared boundary, ``screening``, ``partial`` or ``unavailable``, with the reasons, and whether it
is only a carbon footprint (every category a climate one). Every exchange without a burden in a
category is a gap (``lca/gaps.csv``), excluded from the totals and never counted as 0.

What the flowsheet's declared boundary leaves out is reported beside it, as in the TEA: the
boundary check (:func:`..flows.boundary_gaps`, rules ``cheme.boundary-*``) runs on the flowsheet,
its findings are the report's and its result is ``boundary_check``. It changes neither the
inventory nor the classification: a utility of a step without an energy stream is in no
exchange, and nothing is added for it.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from chemeascode.domains.assessment.flows import BoundaryReport, boundary_gaps
from chemeascode.domains.assessment.lca.allocation import (
    MISSING,
    PROPORTIONAL,
    _released,
    allocate,
)
from chemeascode.domains.assessment.lca.backgrounds import resolve
from chemeascode.domains.assessment.lca.balance import dataset_balance
from chemeascode.domains.assessment.lca.carbon import ccu_findings, pcf, pcf_findings
from chemeascode.domains.assessment.lca.carbon import findings as carbon_findings
from chemeascode.domains.assessment.lca.comparability import NOT_COMPARABLE, effective_scope
from chemeascode.domains.assessment.lca.comparability import verdict as scenario_verdict
from chemeascode.domains.assessment.lca.construction import read_takeoff
from chemeascode.domains.assessment.lca.cutoff import findings as cutoff_findings
from chemeascode.domains.assessment.lca.documentation import findings as dataset_findings
from chemeascode.domains.assessment.lca.elementary import water_balance
from chemeascode.domains.assessment.lca.impacts import (
    FACTORS_FILE,
    GAP_REASONS,
    Gap,
    Impact,
    UnitScore,
    characterise,
    characterise_brightway,
    real_gaps,
    unmapped_gaps,
)
from chemeascode.domains.assessment.lca.inventory import LCA_FILE, Inventory, inventory
from chemeascode.domains.assessment.lca.linking import link_findings
from chemeascode.domains.assessment.lca.mapping_profiles import profile_flows
from chemeascode.domains.assessment.lca.methods import categories as packaged_methods
from chemeascode.domains.assessment.lca.quality import rating, score
from chemeascode.domains.assessment.lca.schemas import (
    CREDITING_MODELS,
    PUBLICATION_ORDER,
    Category,
    DatasetDocumentation,
    DatasetRef,
    FactorFile,
    LcaFile,
    LciDataset,
    Source,
)
from chemeascode.domains.assessment.mto import MTO_CSV
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import LIST_FILES, PLANT_FILE, NotAPlantRepository, Workspace

INVENTORY_CSV = "lca/inventory.csv"
#: The plant's unallocated LCI dataset (``kind: lci_dataset``), for other studies and the Atlas.
DATASET_FILE = "lca/dataset.yaml"
#: The Monte Carlo statistics per category (only when lca.yaml has uncertainty:).
UNCERTAINTY_CSV = "lca/uncertainty.csv"
RESULTS_CSV = "lca/results.csv"
RESULTS_MD = "lca/results.md"
#: Every exchange and category without a burden (header only when there is none).
GAPS_CSV = "lca/gaps.csv"
#: The run manifest: what the results were computed from (inputs, mappings, background,
#: method, settings, software), so a changed one invalidates them (gate lca-current).
MANIFEST_FILE = "lca/manifest.json"
MANIFEST_SCHEMA = "cheme/lca-manifest/v1"
#: How far a result can be read (:func:`classify`).
CLASSIFICATIONS = ("complete", "screening", "partial", "unavailable")
#: Factor statuses that make a result screening.
SCREENING_STATUSES = ("ASSUMED", "PROXY", "ESTIMATE")
#: The factor status of an exchange (:func:`factor_status`), weakest first: a
#: gap, an example factor, a factor ``ASSUMED``, ``PROXY``, ``ESTIMATE``, ``EPD`` or ``PUBLISHED``,
#: a background database's activity or biosphere flow (``database``), or no burden by declaration
#: (``none``: free, a co-product, or an elementary flow outside every method).
FACTOR_STATUSES = (
    "gap",
    "example",
    "ASSUMED",
    "PROXY",
    "ESTIMATE",
    "EPD",
    "PUBLISHED",
    "database",
    "none",
)
#: The factor statuses a published result may rest on (the gate's ``factors-published``).
PUBLISHED_STATUSES = ("EPD", "PUBLISHED", "database", "none")
#: A factor this many years from the study's reference year is flagged.
YEAR_SPAN = 10
#: The files an LCA report is computed from, relative to the root.
REPORT_INPUTS = (
    "process.yaml",
    MATERIALS_FILE,
    FLOWSHEET_FILE,
    LCA_FILE,
    FACTORS_FILE,
    MTO_CSV,
    LIST_FILES["equipment"],
    # where a reactor is declared adiabatic (the boundary check reads it)
    "process/simulation.yaml",
)
BASELINE = "baseline"

INVENTORY_COLUMNS = (
    "key",
    "title",
    "phase",
    "direction",
    "kind",
    "plant",
    "plant_unit",
    "quantity",
    "unit",
    "provenance",
    "mapping",
    "streams",
)
RESULT_COLUMNS = (
    "scenario",
    "category",
    "category_unit",
    "key",
    "basis",
    "quantity",
    "unit",
    "factor",
    "impact",
    "share",
    "phase",
    "status",
    "source",
    "year",
)


def _g(value: float) -> str:
    return f"{value:.6g}"


@dataclass
class LcaReport:
    """The LCA of one case. ``loaded`` is False when an input does not load."""

    root: Path
    inventory: Inventory | None = None
    categories: list[Category] = field(default_factory=list)
    impacts: list[Impact] = field(default_factory=list)
    example: bool = False
    boundary: str = ""
    #: ``factors`` or ``brightway``, and what it read (``lca/factors.yaml``, the project).
    backend: str = ""
    background: str = ""
    #: ``baseline`` first, then the scenario ids of ``lca/lca.yaml``.
    scenarios: list[str] = field(default_factory=list)
    #: Every allocation method (baseline): the functional unit's share and the totals by
    #: category, or why it does not apply.
    comparison: list[dict[str, Any]] = field(default_factory=list)
    #: The Monte Carlo of the baseline (None when lca.yaml asks for none).
    uncertainty: Any = None
    #: Every exchange and category without a burden, by scenario (excluded from the totals).
    gaps: list[Gap] = field(default_factory=list)
    #: The source registry entries the results draw on (factors backend).
    sources: list[Source] = field(default_factory=list)
    #: One of :data:`CLASSIFICATIONS`, and why.
    classification: str = "unavailable"
    reasons: list[str] = field(default_factory=list)
    #: Every category is a climate one: a carbon footprint, not a multi-impact LCA.
    climate_only: bool = False
    #: What the boundary leaves out (no construction, no end of life, ...).
    limitations: list[str] = field(default_factory=list)
    #: What the flowsheet's declared boundary leaves out (:func:`..flows.boundary_gaps`): the
    #: inventory holds only the terminals, so a step's utility in none is in no exchange.
    boundary_check: BoundaryReport | None = None
    #: The most restrictive publication policy of the sources the results draw on, the
    #: sources that make it so, and whether the results may be published (a public policy, or
    #: a restricted one the study's reviewed decision allows).
    publication: str = "public"
    restricted_by: list[str] = field(default_factory=list)
    publishable: bool = True
    #: The scope and the (resolved) factors read, the LCI datasets referenced, and the
    #: identity of each Brightway database used (for the manifest).
    scope: Any = None
    factors: Any = None
    dataset_files: list[str] = field(default_factory=list)
    #: The provider profiles (brightway.mapping_profiles) the mappings were taken from.
    mapping_files: list[str] = field(default_factory=list)
    #: The packaged profiles lca/factors.yaml includes.
    profiles: list[str] = field(default_factory=list)
    databases: dict[str, Any] = field(default_factory=dict)
    #: Fingerprint of each Brightway method's characterisation factors (for the manifest).
    methods: dict[str, Any] = field(default_factory=dict)
    #: The substitution credits the allocation comparison characterised (baseline): published
    #: with the comparison, so their sources count for the publication policy.
    credits: list[Impact] = field(default_factory=list)
    #: Only the foreground inventory was computed (no factors or Brightway needed).
    inventory_only: bool = False
    #: The inventory each scenario characterised, by id, when it differs from the baseline's:
    #: its own flowsheet case (``case:``), or its ``missing:`` and ``proxy:`` declarations.
    scenario_inventories: dict[str, Inventory] = field(default_factory=dict)
    #: The findings each scenario raised itself (its characterisation, its own case's
    #: inventory), by id: a scenario's record carries its own and not the others'.
    scenario_findings: dict[str, list[Finding]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    #: The design's maturity (process.yaml), which caps the default pedigree.
    maturity: str | None = None
    #: The data quality rating of the plant's dataset (:func:`.quality.rating`).
    data_quality: Any = None
    #: The product carbon footprint breakdown of the baseline (:class:`.carbon.Pcf`) when the
    #: study declares carbon_accounting.
    pcf: Any = None
    #: The mass, element, carbon-origin and energy balance of the plant's dataset
    #: (:class:`.balance.DatasetBalance`).
    balance: Any = None
    #: The git commit and the fingerprints of :data:`REPORT_INPUTS` when this was computed.
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def loaded(self) -> bool:
        return self.inventory is not None and not any(f.level == "error" for f in self.findings)

    @property
    def label(self) -> str:
        """What the result is, e.g. ``partial screening carbon footprint``."""
        # climate categories alone are always a screening carbon footprint, never a full LCA
        kind = "screening carbon footprint" if self.climate_only else "LCA"
        if self.classification == "screening":
            return kind if self.climate_only else "screening LCA"
        if self.classification == "partial":
            return f"partial {kind}"
        if self.classification == "complete":
            return "LCA, complete within the declared boundary"
        return f"{kind}: unavailable"

    def totals(self, scenario: str = BASELINE, phase: str | None = None) -> dict[str, float]:
        """Total impact per category id, per functional unit, in *scenario* (and *phase*)."""
        found = {c.id: 0.0 for c in self.categories}
        for impact in self.impacts:
            if impact.scenario == scenario and (phase is None or impact.phase == phase):
                found[impact.category] += impact.value
        return found

    def comparability(self, scenario: str) -> dict[str, list[str] | None]:
        """Per category of *scenario*: the exchanges the baseline characterises that are gaps
        here (its total leaves them out, so it is no lower footprint), or None when every
        contribution is a gap (no total at all, never 0). Absent: the total stands, with the
        gaps listed beside it as everywhere."""
        found: dict[str, list[str] | None] = {}
        gaps = real_gaps([g for g in self.gaps if g.scenario == scenario])
        for category in self.categories:
            base = {
                i.key for i in self.impacts if i.scenario == BASELINE and i.category == category.id
            }
            mine = {
                i.key for i in self.impacts if i.scenario == scenario and i.category == category.id
            }
            gapped = {g.key for g in gaps if g.category == category.id}
            lost = sorted(gapped & (base - mine))
            if lost:
                found[category.id] = lost
            elif gapped and not mine:
                found[category.id] = None
        return found

    @property
    def carbon(self) -> dict[str, Any] | None:
        """The carbon accounting: the study's choices, the carbon traced
        through the plant's dataset and the PCF breakdown; None when the study declares none."""
        inv = self.inventory
        if inv is None or inv.carbon is None or self.scope is None:
            return None
        accounting = self.scope.carbon_accounting
        return {
            "accounting": accounting.model_dump(mode="json", exclude={"pact"}),
            "balance": inv.carbon.as_dict(),
            "pcf": self.pcf.as_dict() if self.pcf is not None else None,
        }

    @property
    def water(self) -> dict[str, Any] | None:
        """The water balance of the plant's dataset (m3 per its basis), or None without a water
        flow (:func:`.elementary.water_balance`)."""
        dataset = self.inventory.dataset if self.inventory is not None else None
        found = water_balance(dataset) if dataset is not None else None
        if found is None:
            return None
        return {"basis": dataset.basis, "unit": "m3", **{k: round(v, 9) for k, v in found.items()}}

    def payload(self) -> dict[str, Any]:
        inv = self.inventory
        return {
            "case": inv.case if inv else None,
            "functional_unit": inv.functional_unit if inv else None,
            "boundary": self.boundary,
            "allocation": {
                "method": inv.method,
                "shares": inv.shares,
                "comparison": self.comparison,
            }
            if inv
            else None,
            "example_factors": self.example,
            "backend": self.backend,
            "background": self.background,
            "classification": self.classification,
            "label": self.label,
            "reasons": list(self.reasons),
            "climate_only": self.climate_only,
            "limitations": list(self.limitations),
            # the boundary check, as the TEA's "boundary": additive
            "boundary_check": self.boundary_check.payload() if self.boundary_check else None,
            "sources": [
                s.model_dump(mode="json", exclude=None if s.scope else {"scope"})
                for s in self.sources
            ],
            "gaps": [asdict(g) for g in self.gaps],
            "publication": {
                "policy": self.publication,
                "publishable": self.publishable,
                "restricted_by": list(self.restricted_by),
            },
            "inventory": [asdict(row) for row in inv.rows] if inv else [],
            "categories": [c.model_dump(mode="json") for c in self.categories],
            "totals": self.totals(),
            # JSON objects lose their order in JavaScript for ids like 2030: the order as a list
            "scenario_ids": list(self.scenarios),
            "scenarios": {s: self.totals(s) for s in self.scenarios},
            # totals that do not stand: per scenario and category, the
            # exchanges the baseline has that are gaps there, or null when every contribution is a
            # gap
            "not_comparable": {
                s: found for s in self.scenarios if (found := self.comparability(s))
            },
            # per scenario: like-for-like, proxy or not comparable with the baseline, why, and
            # the compared factors' differing dimensions
            # (lci-comparison-basis.md)
            "comparability": {s: scenario_verdict(self, s) for s in self.scenarios},
            # what each scenario is (geography, year, electricity, case): additive metadata
            "scenario_details": [
                s.model_dump(
                    mode="json",
                    include={"id", "title", "location", "year", "electricity", "case", "source"},
                )
                for s in (self.scope.scenarios if self.scope is not None else [])
            ],
            "uncertainty": asdict(self.uncertainty) if self.uncertainty is not None else None,
            "water": self.water,
            "data_quality": self.data_quality.as_dict() if self.data_quality else None,
            "carbon": self.carbon,
            "balance": self.balance.as_dict() if self.balance is not None else None,
            # per scenario and exchange: the weakest status of its factors
            "factor_status": {s: factor_status(self, s) for s in self.scenarios or [BASELINE]},
            "factors_published": not unpublished(self),
            "impacts": [asdict(i) for i in self.impacts],
        }

    def to_json(self) -> str:
        return json.dumps(
            {
                **self.payload(),
                "findings": [{**asdict(f), "id": f.id} for f in self.findings],
                "source": self.source.as_dict(),
            },
            indent=2,
        )


def _load(
    root: Path, name: str, model: type[BaseModel], rule: str, hint: str
) -> tuple[Any, str | None, list[Finding]]:
    path = root / name
    if not path.is_file():
        return None, None, [Finding(name, "error", rule, f"no {name}", hint=hint)]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        return (
            None,
            None,
            [Finding(name, "error", rule, f"{name} cannot be read: {failure}", hint=hint)],
        )
    try:
        return model.model_validate(yaml.safe_load(text) or {}), text, []
    except (ValidationError, yaml.YAMLError) as failure:
        first = str(failure).splitlines()
        return (
            None,
            text,
            [
                Finding(
                    name,
                    "error",
                    rule,
                    f"{name} does not load: {' '.join(first[:3])}",
                    hint="cheme validate names the line",
                )
            ],
        )


#: The process-library manifest of a plant repository: its ``maturity`` caps the default
#: pedigree's technological score (:mod:`.quality`).
PROCESS_MANIFEST = "process.yaml"


def maturity(root: Path) -> str | None:
    """The ``maturity`` label of *root*'s process-library manifest, if it has one."""
    path = Path(root) / PROCESS_MANIFEST
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    value = data.get("maturity") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def lca_report(root: Path, inventory_only: bool = False) -> LcaReport:
    """The LCA of the plant repository at *root*, independent of the working directory.

    With *inventory_only*, only the foreground inventory and the unallocated dataset: no
    factors, Brightway project or licensed data needed.

    Raises :class:`NotAPlantRepository` when *root* holds no ``plant.yaml``. Inputs that do not
    load are findings, and ``loaded`` is then False (classification ``unavailable``)."""
    report = _lca_report(Path(root), inventory_only)
    if report.inventory is not None:
        report.findings += report.inventory.notes
        report.data_quality = _data_quality(report)
    if report.inventory is not None and report.inventory.dataset is not None:
        # what the plant's dataset lacks for publication: given in lca/lca.yaml (dataset:)
        report.findings += [
            dataclasses.replace(f, file=LCA_FILE)
            for f in dataset_findings(report.inventory.dataset, DATASET_FILE)
            + cutoff_findings(report.inventory.dataset, DATASET_FILE)
            + (report.balance.findings(DATASET_FILE) if report.balance is not None else [])
        ]
    if report.boundary_check is not None:
        report.findings += report.boundary_check.findings
    if report.classification == "unavailable" and not report.reasons and not inventory_only:
        classify(report)
    return report


def _lca_report(root: Path, inventory_only: bool) -> LcaReport:
    from chemeascode.domains.process.model import load

    if not (root / PLANT_FILE).is_file():
        raise NotAPlantRepository(f"No {PLANT_FILE} in {root}.")
    report = LcaReport(
        root, source=source_revision(root, REPORT_INPUTS), inventory_only=inventory_only
    )
    scope, lca_text, found = _load(
        root,
        LCA_FILE,
        LcaFile,
        "cheme.lca-no-scope",
        "write the goal and scope there (cheme schema lca; cheme init ships one)",
    )
    report.findings += found
    factors = None
    if scope is not None and scope.backend == "factors" and not inventory_only:
        factors, _, found = _load(
            root,
            FACTORS_FILE,
            FactorFile,
            "cheme.lca-no-factors",
            "write the project's factors there (cheme schema lca_factors)",
        )
        report.findings += found
        if factors is not None:
            report.profiles = list(factors.include)
            factors, problems = resolve(factors)
            report.findings += [
                Finding(
                    FACTORS_FILE,
                    "error",
                    "cheme.lca-profile",
                    problem,
                    hint="include a packaged profile (docs/framework/lca.md lists them), and "
                    "keep each category in one unit",
                )
                for problem in problems
            ]
    process, found = load(root)
    report.findings += [f for f in found if f.level == "error"]
    if process is None:
        report.findings.append(
            Finding(
                FLOWSHEET_FILE,
                "error",
                "cheme.lca-no-flowsheet",
                f"no loadable {FLOWSHEET_FILE}: the inventory is the flowsheet's feeds and "
                "products",
                hint="cheme process streams shows what is missing",
            )
        )
    missing_factors = scope is not None and scope.backend == "factors" and factors is None
    if scope is None or process is None or (missing_factors and not inventory_only):
        return report
    if any(f.level == "error" for f in report.findings):
        return report
    # provider profiles map what flows: leaves unmapped
    added, report.mapping_files, found = profile_flows(root, scope, process, LCA_FILE, lca_text)
    report.findings += found
    if any(f.level == "error" for f in found):
        return report
    if added:
        scope = scope.model_copy(update={"flows": [*scope.flows, *added]})
    # what the terminals leave out: reported (its findings last), the inventory is not changed
    report.boundary_check = boundary_gaps(process)
    report.boundary = scope.boundary
    report.backend = scope.backend
    report.limitations = _limitations(scope)
    takeoff, equipment, found = _construction_inputs(root, scope)
    report.findings += found
    if found:
        return report
    report.maturity = maturity(root)
    report.inventory = inventory(
        process,
        scope,
        lca_text,
        takeoff,
        equipment,
        report.maturity,
        load=lambda path: load_dataset(root, path),
    )
    if report.inventory.dataset is not None:
        # the balance gates: mass, elements, carbon by origin, energy
        report.balance = dataset_balance(
            report.inventory.dataset,
            report.maturity,
            scope.carbon_accounting,
            load=lambda path: load_dataset(root, path),
        )
        # construction entries cut off are listed already, from the scope
        report.limitations += [
            f"cut off by the study's criteria: {c.key} ({c.reason})"
            for c in report.inventory.dataset.cutoff
            if not c.key.startswith("construction:")
        ]
    report.findings += report.inventory.findings
    if any(f.level == "error" for f in report.inventory.findings) or inventory_only:
        return report
    report.scenarios = [BASELINE] + [s.id for s in scope.scenarios]
    replacements = {BASELINE: {}}
    for scenario in scope.scenarios:
        replace = scenario.factors if scope.backend == "factors" else scenario.databases
        replacements[scenario.id] = replace
        if not (replace or scenario.case or scenario.missing or scenario.proxy):
            report.findings.append(
                Finding(
                    LCA_FILE,
                    "warning",
                    "cheme.lca-scenario-empty",
                    f"scenario {scenario.id} replaces no "
                    + ("factors" if scope.backend == "factors" else "databases")
                    + f" (backend {scope.backend}): it repeats the baseline",
                    ids=[scenario.id],
                    hint="give it factors: (backend factors) or databases: (backend brightway)",
                )
            )

    for spec in scope.scenarios:
        inv = _scenario_inventory(report, spec, process, scope, lca_text, takeoff, equipment)
        if inv is not report.inventory:
            report.scenario_inventories[spec.id] = inv
    if any(f.level == "error" for f in report.findings):
        return report

    def run(inv, replace, scenario, datasets, gaps=None):
        if scope.backend == "factors":
            return characterise(inv, factors, scope.categories, replace, scenario, datasets, gaps)
        return characterise_brightway(inv, scope.brightway, replace, scenario, datasets, gaps)

    resolver = _Datasets(root, run)
    for scenario, replace in replacements.items():
        gaps: list[Gap] = []
        inv = report.scenario_inventories.get(scenario, report.inventory)
        categories, impacts, found = run(inv, replace, scenario, resolver, gaps)
        report.scenario_findings.setdefault(scenario, []).extend(found)
        seen = {(f.rule, f.message) for f in report.findings}
        report.findings += [f for f in found if (f.rule, f.message) not in seen]
        report.impacts += impacts
        report.gaps += unmapped_gaps(inv, [c.id for c in categories], scenario)
        report.gaps += gaps
        if scenario == BASELINE:
            report.categories = categories
            if not categories:
                break
    if report.categories and not any(f.level == "error" for f in report.findings):
        products = report.inventory.dataset.products() if report.inventory.dataset else []
        if len(products) > 1:
            report.comparison = _comparison(
                report, scope, lambda inv, gaps=None: run(inv, {}, BASELINE, resolver, gaps)
            )
        if scope.uncertainty is not None:
            from chemeascode.domains.assessment.lca.uncertainty import monte_carlo

            report.uncertainty = monte_carlo(
                report.inventory,
                [i for i in report.impacts if i.scenario == BASELINE],
                report.categories,
                scope,
                factors if scope.backend == "factors" else None,
                report.inventory.amount,
            )
    # before the resolver's findings are taken: a dataset loaded here reports its own
    report.findings += link_findings(scope, report.inventory, resolver.load, LCA_FILE, lca_text)
    report.findings += [
        f
        for f in resolver.findings
        if (f.rule, f.message) not in {(g.rule, g.message) for g in report.findings}
    ]
    if scope.backend == "factors":
        report.example = factors.example
        report.background = FACTORS_FILE
        if factors.example:
            report.findings.append(
                Finding(
                    FACTORS_FILE,
                    "warning",
                    "cheme.lca-example-factors",
                    "the factors are an example (example: true): the results characterise "
                    "nothing real",
                    hint="replace every factor with the project's own, each with its status, "
                    "source, year and licence, and remove example: true",
                )
            )
    else:
        report.background = f"Brightway project {scope.brightway.project}"
    report.scope = scope
    report.factors = factors
    report.dataset_files = sorted(p for p, d in resolver.loaded.items() if not isinstance(d, str))
    report.findings += _system_models(report, scope, resolver.loaded)
    used = {s for i in report.impacts + report.credits for s in _ids(i.source_id)}
    registry = {**resolver.registry, **({s.id: s for s in factors.sources} if factors else {})}
    report.sources = [registry[s] for s in sorted(used) if s in registry]
    if scope.backend == "brightway" and report.loaded:
        datasets = [d for d in resolver.loaded.values() if not isinstance(d, str)]
        report.findings += _verify_brightway(report, scope, datasets)
    report.findings += _compatibility(report, scope)
    _publication(report, scope, factors)
    classify(report)
    _carbon(report, scope)
    return report


def _climate_category(report: LcaReport) -> Category | None:
    """The category a PCF is read from: the first climate one, a GWP100 before the others."""
    climate = [c for c in report.categories if _climate(c)]
    preferred = [c for c in climate if "gwp20" not in f"{c.id} {c.elementary or ''}".lower()]
    return (preferred or climate or [None])[0]


def _carbon(report: LcaReport, scope: LcaFile) -> None:
    """The carbon accounting of a PCF study (``carbon_accounting:``): the trace's findings and
    the PCF breakdown of the baseline (:mod:`.carbon`)."""
    accounting = scope.carbon_accounting
    inv = report.inventory
    if accounting is None or inv is None or inv.dataset is None or inv.carbon is None:
        return
    report.findings += carbon_findings(
        inv.carbon, inv.dataset, accounting, LCA_FILE, report.maturity
    )
    category = _climate_category(report)
    if category is None:
        report.findings.append(
            Finding(
                LCA_FILE,
                "warning",
                "cheme.lca-pcf-category",
                "carbon_accounting: no climate category (unit kg CO2-eq): no PCF breakdown",
                hint="report a climate category, e.g. ipcc2021-gwp100",
            )
        )
        return
    impacts = [i for i in report.impacts if i.scenario == BASELINE and i.category == category.id]
    report.findings += ccu_findings(inv, impacts, accounting, LCA_FILE)
    report.pcf = pcf(inv, impacts, category, accounting, inv.carbon, scope.functional_unit.product)
    report.findings += pcf_findings(report.pcf, LCA_FILE)


def _data_quality(report: LcaReport) -> Any:
    """The rating of the plant's dataset, weighted by the baseline's contributions to its first
    climate category where it has one (TfS: a PCF rating), else unweighted."""
    dataset = report.inventory.dataset
    if dataset is None:
        return None
    climate = next((c for c in report.categories if _climate(c)), None)
    contributions: dict[str, float] = {}
    if climate is not None:
        for impact in report.impacts:
            if impact.scenario == BASELINE and impact.category == climate.id:
                contributions[impact.key] = contributions.get(impact.key, 0.0) + impact.value
    return rating(dataset, contributions, climate.id if climate is not None else "")


#: The source id of a contribution from a factor without a registry entry.
UNREGISTERED = "unregistered factors"


def _scenario_inventory(
    report: LcaReport, spec: Any, process: Any, scope: LcaFile, lca_text, takeoff, equipment
) -> Inventory:
    """The inventory scenario *spec* characterises: the baseline's (the same object when the
    scenario changes nothing in it), derived from the scenario's own flowsheet case when it
    names one, with its ``missing:`` and ``proxy:`` declarations applied. In a regional
    scenario (``location:``) a background the scenario replaces is judged by its own status:
    the baseline mapping's ``proxy:`` note described the baseline's background, not this one."""
    base = report.inventory
    inv = base
    if spec.case is not None and spec.case != base.case:
        inv = inventory(
            process,
            scope.model_copy(update={"case": spec.case}),
            lca_text,
            takeoff,
            equipment,
            report.maturity,
            load=lambda path: load_dataset(report.root, path),
        )
        # every finding of the case's own inventory (an incomplete stream, a flow left out of
        # transport, ...), named for the scenario: never dropped, never another case's
        own = [
            dataclasses.replace(
                finding,
                message=f"scenario {spec.id} (case {spec.case}): {finding.message}",
                ids=[*finding.ids, spec.id],
            )
            for finding in inv.findings
        ]
        report.findings += own
        report.scenario_findings.setdefault(spec.id, []).extend(own)
        if inv.dataset is None:
            return base
    backgrounds = dict(inv.backgrounds)
    rows = list(inv.rows)
    if spec.regional:
        for key, background in backgrounds.items():
            replaced = background.factor in spec.factors or (
                background.activity is not None and background.activity.database in spec.databases
            )
            if background.proxy and replaced:
                backgrounds[key] = background.model_copy(update={"proxy": ""})
    unknown = []
    for pattern, why in spec.proxy.items():
        keys = [k for k in backgrounds if fnmatchcase(k, pattern)]
        unknown += [] if keys else [pattern]
        for key in keys:
            backgrounds[key] = backgrounds[key].model_copy(update={"proxy": why})
    for pattern, why in spec.missing.items():
        keys = [r.key for r in rows if fnmatchcase(r.key, pattern)]
        unknown += [] if keys else [pattern]
        for key in keys:
            backgrounds.pop(key, None)
        rows = [
            dataclasses.replace(r, mapping=MISSING + why) if fnmatchcase(r.key, pattern) else r
            for r in rows
        ]
    if unknown:
        report.findings.append(
            Finding(
                LCA_FILE,
                "warning",
                "cheme.lca-scenario-key",
                f"scenario {spec.id}: missing: or proxy: names no exchange of case {inv.case}: "
                f"{', '.join(unknown)}",
                ids=[spec.id, *unknown],
                hint="use exchange keys of lca/inventory.csv (feed:<id>, construction:<id>, ...; "
                "globs allowed)",
            )
        )
    if inv is base and backgrounds == base.backgrounds and rows == base.rows:
        return base
    return dataclasses.replace(inv, rows=rows, backgrounds=backgrounds)


def _ids(text: str) -> list[str]:
    """The comma-joined ids of an impact's ``source_id``, ``status`` or ``location``."""
    return [part for part in text.split(",") if part]


def _brightway_databases(report: LcaReport, scope: LcaFile, datasets: list) -> list[str]:
    """Every Brightway database the study reads: its mappings', the substitutes', those of the
    datasets it references, the biosphere, the scenarios' replacements and the expected ones."""
    names = set(scope.brightway.expect)
    if scope.brightway.biosphere:
        names.add(scope.brightway.biosphere)
    backgrounds = [
        *report.inventory.backgrounds.values(),
        *scope.allocation.substitution.values(),
        *(e.link for d in datasets for e in d.exchanges if e.link is not None),
    ]
    for background in backgrounds:
        for ref in (background.activity, background.biosphere):
            if ref is not None:
                names.add(ref.database)
    for scenario in scope.scenarios:
        names |= set(scenario.databases.values())
    return sorted(names)


def _verify_brightway(report: LcaReport, scope: LcaFile, datasets: list) -> list[Finding]:
    """Each database's recorded provider, version and system model against ``expect``; a
    warning for the databases matched by name only."""
    from chemeascode.integrations import brightway as bw

    names = _brightway_databases(report, scope, datasets)
    try:
        report.databases = bw.databases(scope.brightway.project, names)
        report.methods = bw.method_fingerprints(
            scope.brightway.project, [tuple(c.method) for c in scope.brightway.categories]
        )
    except (bw.BrightwayUnavailable, LookupError):
        return []  # the characterisation already says so
    found: list[Finding] = []
    unverified = []
    for name in names:
        info = report.databases.get(name)
        if info is None:
            if name in scope.brightway.expect:
                found.append(
                    Finding(
                        LCA_FILE,
                        "error",
                        "cheme.lca-brightway-identity",
                        f"database {name} of brightway.expect is not in project "
                        f"{scope.brightway.project}",
                        ids=[name],
                        hint="import it, or correct the name in brightway.expect",
                    )
                )
            continue
        expected = scope.brightway.expect.get(name)
        if expected is None:
            unverified.append(name)
            continue
        for key in bw.IDENTITY:
            want = getattr(expected, key)
            if want and info[key] != want:
                found.append(
                    Finding(
                        LCA_FILE,
                        "error",
                        "cheme.lca-brightway-identity",
                        f"database {name} records {key} {info[key] or '(none)'!r}, the study "
                        f"expects {want!r}",
                        ids=[name],
                        hint="import the database the study names. Only once you have checked "
                        "that the imported one is it (its release notes, the importer's log), "
                        f"record that: bd.projects.set_current({scope.brightway.project!r}); "
                        f"bd.databases[{name!r}][{key!r}] = {want!r}; bd.databases.flush()",
                    )
                )
    if unverified:
        found.append(
            Finding(
                LCA_FILE,
                "warning",
                "cheme.lca-brightway-unverified",
                f"databases matched by name only: {', '.join(unverified)}",
                ids=unverified,
                hint="give brightway.expect: {<name>: {provider, version, system_model}}",
            )
        )
    return found


def _source_policy(
    source_id: str, scope: LcaFile, factors: FactorFile | None, registry: dict[str, Source]
) -> str:
    if source_id.startswith("method:"):
        return "public"  # packaged characterisation factors (IPCC), published values
    if source_id.startswith("brightway:"):
        if scope.brightway is None:
            return "restricted"
        database = source_id.partition("/")[2]
        identity = scope.brightway.expect.get(database)
        if identity is None:
            # a database known by name only cannot be shown to be an open one
            return "local" if scope.brightway.publication == "local" else "restricted"
        return identity.publication or scope.brightway.publication
    if source_id in registry:
        return registry[source_id].publication
    if source_id == UNREGISTERED and factors is not None:
        return factors.publication
    return "restricted"


def _publication(report: LcaReport, scope: LcaFile, factors: FactorFile | None) -> None:
    """The most restrictive policy of every source the impacts draw on, and whether the results
    may be published: policy public, or restricted with the study's reviewed decision."""
    policies: dict[str, str] = {}
    registry = {s.id: s for s in report.sources}
    # every contribution, the allocation comparison's credits too (they are published with it)
    for impact in report.impacts + report.credits:
        for source_id in _ids(impact.source_id) or [UNREGISTERED]:
            policies[source_id] = _source_policy(source_id, scope, factors, registry)
    order = PUBLICATION_ORDER
    report.publication = max(policies.values(), key=order.index, default="public")
    report.restricted_by = sorted(k for k, v in policies.items() if v != "public")
    decision = scope.publication
    report.publishable = report.publication == "public" or (
        report.publication == "restricted" and decision is not None and decision.allow_restricted
    )


def _system_models(report: LcaReport, scope: LcaFile, loaded: dict) -> list[Finding]:
    """What mixes system models: a credit (a negative contribution of an
    end-of-life or recyclable output) in a study that does not credit, and background datasets of a
    crediting system model in one that does not, or the reverse."""
    model = scope.model
    found = []
    if model not in CREDITING_MODELS and report.inventory.dataset is not None:
        # end of life and recyclable outputs; a waste's treatment may return water (negative)
        outputs = {
            e.key
            for e in report.inventory.dataset.exchanges
            if e.type == "output"
            and (e.phase == "end-of-life" or (e.treatment and e.treatment.kind != "waste"))
        }
        credited = sorted(
            {
                i.key
                for i in report.impacts
                if i.scenario == BASELINE and i.key in outputs and i.value < 0
            }
        )
        if credited:
            found.append(
                Finding(
                    LCA_FILE,
                    "warning",
                    "cheme.lca-cutoff-credit",
                    f"outputs with a negative impact (a credit in their background) under system "
                    f"model {model}: {', '.join(credited)}; a cut-off study gives no credits",
                    ids=credited,
                    hint="classify them (kind: recyclable, or treatment: {kind: recyclable}): "
                    "burden-free under cut-off; the credit goes to credit: and counts only "
                    "with system_model: substitution",
                )
            )
    crediting = model in CREDITING_MODELS
    mixed = sorted(
        path
        for path, dataset in loaded.items()
        if not isinstance(dataset, str)
        and dataset.system_model is not None
        and (dataset.system_model in CREDITING_MODELS) != crediting
    )
    if mixed:
        found.append(
            Finding(
                LCA_FILE,
                "warning",
                "cheme.lca-system-model-mixed",
                f"background datasets of another system model than the study's ({model}): "
                f"{', '.join(mixed)}",
                ids=mixed,
                hint="never mix: use datasets built under the study's system model (the "
                "library's cutoff build, or its labelled substitution variant)",
            )
        )
    return found


def _climate(category: Category) -> bool:
    """A climate category: its unit is CO2-equivalent (kg CO2-eq, t CO2e, ...)."""
    unit = category.unit.lower().replace(" ", "").replace("_", "-")
    return "co2" in unit


def _limitations(scope: LcaFile) -> list[str]:
    """What the declared boundary leaves out, stated so that it is not silently assumed absent."""
    found = []
    if scope.boundary == "gate-to-gate":
        found.append("gate-to-gate: no upstream supply chain")
    if not scope.construction:
        found.append("construction (infrastructure, equipment) not included")
    found += [
        f"cut off by the study's criteria: construction {e.id} ({e.cutoff})"
        for e in scope.construction
        if e.cutoff
    ]
    if not scope.end_of_life:
        found.append("end of life of the plant not included")
    if not scope.transport:
        found.append("transport of supplies not included")
    return found


#: Geography codes that name the same place.
_PLACES = {"UK": "GB"}


def _place(code: str) -> str:
    code = code.strip().upper()
    head, sep, rest = code.partition("-")
    return _PLACES.get(head, head) + sep + rest


def _within(location: str, site: str) -> bool:
    """Whether a factor of *location* represents *site*: the same place, or a region of it
    containing the site (GB for GB-ENG). GLO and RER-like aggregates are other geographies."""
    location, site = _place(location), _place(site)
    return location == site or site.startswith(location + "-")


def _method(text: str) -> str:
    """A characterisation method's basis, normalised: the IPCC assessment report it rests on
    (AR4, AR5, AR6, or a mix), else the text."""
    upper = text.upper()
    reports = [r for r in ("AR4", "AR5", "AR6") if r in upper]
    if "IPCC 2021" in upper or "IPCC2021" in upper:
        reports.append("AR6")
    if "IPCC 2013" in upper:
        reports.append("AR5")
    if "IPCC 2007" in upper:
        reports.append("AR4")
    found = sorted(set(reports))
    return "/".join(found) if found else " ".join(text.lower().split())


def _compatibility(report: LcaReport, scope: LcaFile) -> list[Finding]:
    """Factors of another geography or reference year than the study's, categories whose
    contributions rest on different characterisation methods, and what could not be checked
    (no study location or year, contributions without one)."""
    found: list[Finding] = []

    def warn(
        rule: str, message: str, ids: list[str], hint: str, file: str = LCA_FILE, level="warning"
    ) -> None:
        found.append(Finding(file, level, rule, message, ids=ids, hint=hint))

    # the packaged methods characterise elementary flows everywhere: no geography or year
    baseline = [
        i
        for i in report.impacts
        if i.scenario == BASELINE and not i.source_id.startswith("method:")
    ]
    unchecked: list[str] = []
    if not scope.location:
        unchecked.append("lca/lca.yaml gives no location")
    elif placeless := sorted({i.basis for i in baseline if not i.location}):
        unchecked.append(f"{len(placeless)} contributions without a geography")
    if scope.location:
        other = sorted(
            {
                i.basis
                for i in baseline
                if i.location and not all(_within(loc, scope.location) for loc in _ids(i.location))
            }
        )
        if other:
            warn(
                "cheme.lca-geography",
                f"{len(other)} factors represent another geography than the plant's "
                f"({scope.location}): {', '.join(other)}",
                other,
                "use factors of the plant's geography, or state the proxy (proxy:) and read the "
                "result as screening",
            )
    if scope.year is None:
        unchecked.append("lca/lca.yaml gives no reference year")
    elif yearless := sorted({i.basis for i in baseline if i.year is None}):
        unchecked.append(f"{len(yearless)} contributions without a reference year")
    if scope.year is not None:
        old = sorted(
            {
                i.basis
                for i in baseline
                if i.year is not None and abs(i.year - scope.year) > YEAR_SPAN
            }
        )
        if old:
            warn(
                "cheme.lca-reference-year",
                f"{len(old)} factors are more than {YEAR_SPAN} years from the study's "
                f"reference year {scope.year}: {', '.join(old)}",
                old,
                "use more recent data, or read the result as screening",
            )
    if unchecked:
        warn(
            "cheme.lca-unchecked",
            "geography or reference year not checked: " + "; ".join(unchecked),
            [],
            "give lca/lca.yaml location and year, and factors their location and year",
            level="info",
        )
    found += _scenario_compatibility(report, scope)
    methods = {s.id: s.method for s in report.sources if s.method}
    elementary = {
        f"method:{key.partition('-')[0]}": value["method"]
        for key, value in packaged_methods().items()
    }
    everything = [i for i in report.impacts if i.scenario == BASELINE]
    for category in report.categories:
        used: set[str] = set()
        declared: dict[str, set[str]] = {"basis": set(), "gases": set()}
        for i in everything:
            if i.category != category.id:
                continue
            fscope, _ = effective_scope(report.factors, i.basis)
            for dim in declared:
                if getattr(fscope, dim) is not None:
                    declared[dim].add(getattr(fscope, dim))
            if fscope.gases == "co2" and fscope.gwp is None:
                # CO2 only: no GWP basis applies, but it is still a different method from a
                # CO2e factor (scoped or read from its source's text)
                used.add("CO2 only")
                continue
            for s in _ids(i.source_id):
                label = fscope.gwp or (
                    _method(methods.get(s) or elementary.get(s, ""))
                    if methods.get(s) or elementary.get(s)
                    else None
                )
                if label:
                    used.add(label)
        parts = []
        if len(used) > 1:
            parts.append(f"characterisation methods: {'; '.join(sorted(used))}")
        parts += [
            f"{dim}: {'; '.join(sorted(values))}"
            for dim, values in declared.items()
            if len(values) > 1
        ]
        if parts:
            warn(
                "cheme.lca-method-mix",
                f"{category.id}: the contributions rest on different {' | '.join(parts)}",
                [category.id],
                "use one method throughout, or read the result as screening",
                FACTORS_FILE,
            )
    return found


def _scenario_compatibility(report: LcaReport, scope: LcaFile) -> list[Finding]:
    """Each regional scenario's contributions against its own geography and reference year
    (the study's year when it gives none): a background of another country (the baseline's UK
    grid kept in an NL scenario) is named, never relabelled."""
    found: list[Finding] = []
    for spec in scope.scenarios:
        if not spec.regional and spec.year is None:
            continue
        # a background the scenario itself declares a proxy is disclosed (and marked PROXY); the
        # baseline mapping's proxy note spoke of the baseline's geography, not this one
        mine = [
            i
            for i in report.impacts
            if i.scenario == spec.id
            and not i.source_id.startswith("method:")
            and not any(fnmatchcase(i.key, pattern) for pattern in spec.proxy)
        ]
        other = sorted(
            {
                i.basis
                for i in mine
                if i.location and not all(_within(loc, spec.location) for loc in _ids(i.location))
            }
        )
        if other and spec.regional:
            found.append(
                Finding(
                    LCA_FILE,
                    "warning",
                    "cheme.lca-scenario-geography",
                    f"scenario {spec.id}: {len(other)} backgrounds represent another geography "
                    f"than the scenario's ({spec.location}): {', '.join(other)}",
                    ids=[spec.id, *other],
                    hint=f"replace them with backgrounds of {spec.location} (factors:), or "
                    "declare them proxy: (with why) or missing: in the scenario",
                )
            )
        placeless = sorted({i.basis for i in mine if not i.location})
        year = spec.year if spec.year is not None else scope.year
        old = (
            sorted({i.basis for i in mine if i.year is not None and abs(i.year - year) > YEAR_SPAN})
            if year is not None
            else []
        )
        if old:
            found.append(
                Finding(
                    LCA_FILE,
                    "warning",
                    "cheme.lca-scenario-year",
                    f"scenario {spec.id}: {len(old)} backgrounds are more than {YEAR_SPAN} years "
                    f"from its reference year {year}: {', '.join(old)}",
                    ids=[spec.id, *old],
                    hint="use backgrounds of the scenario's time, or read it as screening",
                )
            )
        placeless = placeless if spec.regional else []
        if placeless or year is None:
            what = [f"{len(placeless)} backgrounds without a geography"] if placeless else []
            what += ["no reference year"] if year is None else []
            found.append(
                Finding(
                    LCA_FILE,
                    "info",
                    "cheme.lca-scenario-unchecked",
                    f"scenario {spec.id}: not checked: {'; '.join(what)}",
                    ids=[spec.id],
                    hint="give the factors their location and the scenario its year",
                )
            )
    return found


def classify(report: LcaReport) -> None:
    """Set ``classification``, ``reasons`` and ``climate_only`` of *report* by explicit criteria
    on the baseline (the scenarios' gaps are marked in their columns):

    - ``unavailable``: the LCA does not compute (an error), or no category;
    - ``partial``: an exchange has no burden in a category (a gap; an elementary flow outside a
      method's scope is none);
    - ``screening``: no gap, but example factors, a contribution ASSUMED, PROXY or ESTIMATE
      (also inside a referenced dataset), climate categories only, a geography, reference-year
      or method-mix warning, or geography and year that could not be checked;
    - ``complete``: none of these: every exchange characterised in every category with
      published or declared data of the plant's geography and time, within the declared
      boundary. Complete is not validated: the review judges whether the mapping and the data
      are right.
    """
    report.climate_only = bool(report.categories) and all(_climate(c) for c in report.categories)
    if not report.loaded or not report.categories:
        report.classification = "unavailable"
        report.reasons = ["the LCA does not compute" if not report.loaded else "no category"]
        return
    reasons: list[str] = []
    gaps = real_gaps([g for g in report.gaps if g.scenario == BASELINE])
    if gaps:
        keys = sorted({g.key for g in gaps})
        reasons.append(f"{len(keys)} exchanges without a burden in some category: gaps")
    statuses = sorted(
        {s for i in report.impacts if i.scenario == BASELINE for s in _ids(i.status)}
        & set(SCREENING_STATUSES)
    )
    if report.example:
        reasons.append("example factors")
    if statuses:
        reasons.append(f"factors {', '.join(statuses)}")
    if report.climate_only:
        reasons.append("climate categories only: a carbon footprint, not a multi-impact LCA")
    flagged = {"cheme.lca-geography", "cheme.lca-reference-year", "cheme.lca-method-mix"}
    for rule in sorted({f.rule for f in report.findings if f.rule in flagged}):
        reasons.append(rule.removeprefix("cheme.lca-").replace("-", " ") + " mismatch")
    if any(f.rule == "cheme.lca-unchecked" for f in report.findings):
        reasons.append("geography or reference year not checked")
    report.reasons = reasons
    if gaps:
        report.classification = "partial"
    elif reasons:
        report.classification = "screening"
    else:
        report.classification = "complete"


def factor_status(report: LcaReport, scenario: str = BASELINE) -> dict[str, str]:
    """The factor status of every exchange of *scenario* (:data:`FACTOR_STATUSES`), by key: the
    weakest of its contributions over the categories. A gap (no burden in some category, not one
    outside a method) is ``gap``; with example factors (``example: true``) every contribution of
    ``lca/factors.yaml`` is ``example``; a Brightway contribution without a status of its own is
    ``database``; an exchange that contributes nothing and is no gap is ``none``. Inside a
    referenced dataset the weakest status travels up (its contributions' statuses)."""
    rank = {s: i for i, s in enumerate(FACTOR_STATUSES)}
    found: dict[str, str] = {}

    def weaker(key: str, status: str) -> None:
        if key not in found or rank[status] < rank[found[key]]:
            found[key] = status

    inv = report.scenario_inventories.get(scenario, report.inventory)
    for row in inv.rows if inv is not None else []:
        found[row.key] = "none"
    for impact in report.impacts:
        if impact.scenario != scenario:
            continue
        # example factors: any contribution not wholly a packaged method's (a dataset's
        # source_id joins all of its sources)
        if report.example and not all(s.startswith("method:") for s in _ids(impact.source_id)):
            weaker(impact.key, "example")
            continue
        for status in _ids(impact.status) or ["database"]:
            weaker(impact.key, status if status in rank else "gap")
    for gap in real_gaps([g for g in report.gaps if g.scenario == scenario]):
        weaker(gap.key, "gap")
    return found


def unpublished(report: LcaReport) -> list[str]:
    """Why the factors of *report* do not meet ``factors-published`` (empty when they do): each
    exchange, of the baseline and every scenario, whose factor status is not in
    :data:`PUBLISHED_STATUSES`, with its status."""
    problems: list[str] = []
    for scenario in report.scenarios or [BASELINE]:
        for key, status in factor_status(report, scenario).items():
            if status not in PUBLISHED_STATUSES:
                where = "" if scenario == BASELINE else f" (scenario {scenario})"
                problems.append(f"{key}: factor status {status}{where}")
    return problems


class _Datasets:
    """Resolves dataset backgrounds: loads the dataset, allocates one unit of the product and
    characterises it with the study's backend (recursively; a cycle is an error)."""

    def __init__(self, root: Path, run: Any) -> None:
        self.root = root
        self.run = run
        self.loaded: dict[str, LciDataset | str] = {}
        self.stack: list[str] = []
        self.memo: dict[tuple, UnitScore | str] = {}
        #: Warnings found while resolving (unlinked exchanges), once per dataset.
        self.findings: list[Finding] = []
        #: The source registry entries of the datasets read (externally supplied amounts).
        self.registry: dict[str, Source] = {}

    def load(self, path: str) -> LciDataset | str:
        if path not in self.loaded:
            self.loaded[path] = load_dataset(self.root, path)
            if not isinstance(self.loaded[path], str):
                from chemeascode.domains.assessment.lca.estimate import (
                    owner_maturity,
                    tier_findings,
                )

                self.findings += dataset_findings(self.loaded[path], path)
                self.findings += cutoff_findings(self.loaded[path], path, background=True)
                # a generated estimate (Tier 0 or 1): its tier, balance and caps
                self.findings += tier_findings(self.loaded[path], path, owner_maturity(self.root))
                # an open balance of a referenced dataset, at its own
                # tolerance
                self.findings += [
                    f
                    for f in dataset_balance(self.loaded[path], load=self.load).findings(path)
                    if f.level == "warning"
                ]
                # nothing goes unscored: the default pedigree where the dataset gives none
                self.loaded[path] = score(self.loaded[path])
        return self.loaded[path]

    def __call__(self, ref: DatasetRef, scenario: str, replace: dict[str, str]) -> UnitScore | str:
        key = (ref.path, ref.product, ref.allocation, tuple(sorted(replace.items())), scenario)
        if key not in self.memo:
            self.memo[key] = self._score(ref, scenario, replace)
        return self.memo[key]

    def _score(self, ref: DatasetRef, scenario: str, replace: dict[str, str]) -> UnitScore | str:
        dataset = self.load(ref.path)
        if isinstance(dataset, str):
            return dataset
        if ref.path in self.stack:
            return f"dataset cycle: {' -> '.join([*self.stack, ref.path])}"
        product = dataset.product(ref.product)
        if product is None:
            names = ", ".join(e.key for e in dataset.products())
            return f"{ref.path} has no product {ref.product} (its products: {names})"
        method = ref.allocation or (dataset.allocation.method if dataset.allocation else "mass")
        allocated = allocate(dataset, product.key, 1.0, method, dataset.allocation)
        if allocated.problem:
            return f"{ref.path}: {method} allocation: {allocated.problem}"
        unlinked = [
            e.key
            for e in dataset.exchanges
            if e.type != "product"
            and not e.free
            and (e.link is None or e.link.missing)
            and not _released(e)
        ]
        if unlinked and dataset.scope == "linked":
            return (
                f"{ref.path} is scope linked, but has exchanges without background: "
                f"{', '.join(unlinked)}"
            )
        if unlinked and not any(f.ids == [ref.path] for f in self.findings):
            self.findings.append(
                Finding(
                    ref.path,
                    "warning",
                    "cheme.lca-dataset-unlinked",
                    f"{len(unlinked)} exchanges of {ref.path} have no background: gaps in this "
                    f"study, not in the totals: {', '.join(unlinked)}",
                    ids=[ref.path],
                    hint="link them in the dataset (link: factor, activity, dataset), or mark them "
                    "free",
                )
            )
        inv = Inventory(
            case="",
            functional_unit=f"1 {product.unit} {product.key}",
            method=method,
            shares=allocated.shares,
            rows=allocated.rows,
            backgrounds=allocated.backgrounds,
        )
        self.stack.append(ref.path)
        inner: list[Gap] = []
        try:
            categories, impacts, found = self.run(inv, replace, scenario, self, inner)
        finally:
            self.stack.pop()
        errors = [f for f in found if f.level == "error"]
        if errors:
            return f"{ref.path}: {errors[0].message}"
        inner += [
            Gap(
                g.category,
                g.key,
                "dataset-unlinked" if g.reason == "unmapped" else g.reason,
                g.quantity,
                g.unit,
                g.phase,
                scenario,
                g.detail,
            )
            for g in unmapped_gaps(inv, [c.id for c in categories], scenario)
        ]
        values: dict[str, float] = {}
        for impact in impacts:
            values[impact.category] = values.get(impact.category, 0.0) + impact.value
        # externally supplied amounts keep their source's terms in the study that uses them
        self.registry.update({s.id: s for s in dataset.sources})
        # a contribution from a factor without a registry entry keeps that marker upstream
        unregistered = {UNREGISTERED} if any(not i.source_id for i in impacts) else set()
        sources = (
            unregistered
            | {s for i in impacts for s in _ids(i.source_id)}
            | {
                e.source_id
                for e in dataset.exchanges
                if e.source_id and e.type != "product" and not e.free
            }
        )
        # every category of the run: 0 where no exchange contributes; the gaps travel separately
        for category in categories:
            values.setdefault(category.id, 0.0)
        return UnitScore(
            product.unit,
            values,
            f"dataset:{ref.path}#{product.key.split(':', 1)[1]} ({method})",
            [
                Gap(
                    g.category,
                    f"{ref.path}#{g.key}",
                    g.reason,
                    g.quantity,
                    g.unit,
                    g.phase,
                    scenario,
                    g.detail,
                )
                for g in inner
            ],
            sources,
            {s for i in impacts for s in _ids(i.status)},
            {s for i in impacts for s in _ids(i.location)} | ({dataset.location} - {""}),
            {i.year for i in impacts if i.year is not None}
            | ({dataset.year} if dataset.year is not None else set()),
        )


def load_dataset(root: Path, path: str) -> LciDataset | str:
    """The LCI dataset at *path* (from *root*, inside it), or why it does not load."""
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        return f"{path} is outside the repository"
    if not target.is_file():
        return f"no dataset {path}"
    try:
        return LciDataset.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
    except (OSError, UnicodeDecodeError, ValidationError, yaml.YAMLError) as failure:
        return f"{path} does not load: {' '.join(str(failure).splitlines()[:3])}"


def dataset_paths(lca_text: str | None, read: Any) -> list[str]:
    """Every dataset file *lca_text* references, recursively (through each dataset's own
    links), and the provider profiles it selects, read with ``read(path) -> text | None``: what
    a copy of the inputs must hold."""
    found: list[str] = []

    def refs(data: Any) -> list[str]:
        out = []
        if isinstance(data, dict):
            ref = data.get("dataset")
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                out.append(ref["path"])
            for value in data.values():
                out += refs(value)
        elif isinstance(data, list):
            for value in data:
                out += refs(value)
        return out

    try:
        data = yaml.safe_load(lca_text or "") or {}
    except yaml.YAMLError:
        return found
    todo = refs(data)
    # the provider profiles it selects, read so a copy holds them too
    brightway = data.get("brightway") if isinstance(data, dict) else None
    profiles = brightway.get("mapping_profiles") if isinstance(brightway, dict) else None
    for path in profiles if isinstance(profiles, list) else []:
        if isinstance(path, str) and path not in found:
            found.append(path)
            read(path)
    while todo:
        path = todo.pop()
        if path in found:
            continue
        found.append(path)
        text = read(path)
        if text:
            try:
                todo += refs(yaml.safe_load(text) or {})
            except yaml.YAMLError:
                continue
    return found


def _comparison(report: LcaReport, scope: LcaFile, run: Any) -> list[dict[str, Any]]:
    """Every allocation method's totals (baseline). Proportional methods and ``none`` scale the
    burdens by the functional unit's share; substitution takes the whole burden plus the credits
    of the other products, characterised here."""
    inv = report.inventory
    fu = scope.functional_unit.product
    current = inv.shares.get(fu, 1.0) if inv.method != "substitution" else 1.0
    burden = {c.id: 0.0 for c in report.categories}
    for impact in report.impacts:
        if impact.scenario == BASELINE and not impact.key.startswith("substitution:"):
            burden[impact.category] += impact.value
    found = []
    for method, shares, why in inv.comparison:
        entry: dict[str, Any] = {"method": method, "current": method == inv.method}
        if shares is None:
            found.append({**entry, "share": None, "totals": None, "problem": why})
            continue
        share = shares.get(fu, 0.0)
        if method in PROPORTIONAL or method == "none":
            totals = {k: v / current * share for k, v in burden.items()}
        else:
            allocated = allocate(inv.dataset, fu, inv.amount, method, scope.allocation, inv.totals)
            credits = Inventory(
                case=inv.case,
                functional_unit=inv.functional_unit,
                method=method,
                rows=[r for r in allocated.rows if r.key.startswith("substitution:")],
                backgrounds=allocated.backgrounds,
            )
            gaps: list[Gap] = []
            categories, impacts, problems = run(credits, gaps)
            errors = [f for f in problems if f.level == "error"]
            if errors:
                found.append({**entry, "share": 1.0, "totals": None, "problem": errors[0].message})
                continue
            # a credit without a burden is no credit of 0: substitution does not apply then
            gaps = real_gaps(gaps + unmapped_gaps(credits, [c.id for c in categories], BASELINE))
            if gaps:
                keys = ", ".join(sorted({g.key for g in gaps}))
                found.append(
                    {
                        **entry,
                        "share": 1.0,
                        "totals": None,
                        "problem": f"substitutes without a burden in some category: {keys}",
                    }
                )
                continue
            totals = {k: v / current for k, v in burden.items()}
            report.credits += impacts
            for impact in impacts:
                totals[impact.category] += impact.value
        found.append({**entry, "share": share, "totals": totals, "problem": ""})
    return found


UNCERTAINTY_COLUMNS = (
    "category",
    "unit",
    "deterministic",
    "mean",
    "median",
    "sd",
    "p2_5",
    "p97_5",
    "iterations",
    "seed",
)


def _g4(value: float) -> str:
    """Four significant digits: a sample's statistics, stable across platforms."""
    return f"{value:.4g}"


def uncertainty_csv(report: LcaReport) -> str:
    """The Monte Carlo statistics per category (``lca/uncertainty.csv``; empty without)."""
    if report.uncertainty is None:
        return ""
    units = {c.id: c.unit for c in report.categories}
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(UNCERTAINTY_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for s in report.uncertainty.statistics:
        writer.writerow(
            {
                "category": s.category,
                "unit": units.get(s.category, ""),
                "deterministic": _g4(s.deterministic),
                "mean": _g4(s.mean),
                "median": _g4(s.median),
                "sd": _g4(s.sd),
                "p2_5": _g4(s.low),
                "p97_5": _g4(s.high),
                "iterations": report.uncertainty.iterations,
                "seed": report.uncertainty.seed,
            }
        )
    return buffer.getvalue()


GAP_COLUMNS = (
    "scenario",
    "category",
    "key",
    "reason",
    "quantity",
    "unit",
    "phase",
    "detail",
)


def gaps_csv(report: LcaReport) -> str:
    """Every exchange and category without a burden (``lca/gaps.csv``; the header alone when
    there is none): the quantities the totals exclude."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(GAP_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for gap in report.gaps:
        writer.writerow(
            {
                "scenario": gap.scenario,
                "category": gap.category,
                "key": gap.key,
                "reason": gap.reason,
                "quantity": "" if gap.quantity is None else _g(gap.quantity),
                "unit": gap.unit,
                "phase": gap.phase,
                "detail": gap.detail,
            }
        )
    return buffer.getvalue()


def _sha(root: Path, path: str) -> str | None:
    """sha256 of *path* with normalised line endings (the same on every checkout)."""
    target = root / path
    if not target.is_file():
        return None
    return "sha256:" + hashlib.sha256(target.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _minor(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return ".".join(version(name).split(".")[:2])
    except PackageNotFoundError:
        return ""


#: The parts of lca/lca.yaml that link the foreground to its background.
_MAPPING_FIELDS = {
    "flows",
    "construction",
    "consumables",
    "maintenance",
    "transport",
    "end_of_life",
    "allocation",
}


def _manifest_sources(report: LcaReport) -> list[dict[str, Any]]:
    """The sources the results draw on, with what a consumer must show with the numbers (title,
    provider, URL, licence, attribution) and their version, checksum and policy."""
    return [
        {
            "id": s.id,
            "title": s.title,
            "provider": s.provider,
            "version": s.version,
            "url": s.url,
            "licence": s.licence,
            "attribution": s.attribution,
            "checksum": s.checksum,
            "publication": s.publication,
        }
        for s in report.sources
    ]


def manifest(report: LcaReport) -> dict[str, Any]:
    """The run manifest (``lca/manifest.json``): the functional unit, boundary and allocation,
    fingerprints of every input file and referenced dataset, the sha256 of ``results.csv``, a
    hash of the mappings, the background (factor files and packaged profiles with their
    sources' versions and checksums, or the Brightway databases' identity and size and its
    methods' factor sets), the categories, the settings,
    the software, and the result's class and publication policy. Deterministic: no commit, no
    time, no absolute path, so it changes only when what the results rest on changes."""
    scope = report.scope
    inv = report.inventory
    inputs = {}
    construction = {e.takeoff for e in scope.construction} if scope is not None else set()
    unread = {MTO_CSV} if "mto" not in construction else set()
    if "equipment" not in construction:
        unread.add(LIST_FILES["equipment"])
    for path in (
        *(p for p in REPORT_INPUTS if p not in unread),
        *report.dataset_files,
        *report.mapping_files,
    ):
        sha = _sha(report.root, path)
        if sha is not None:
            inputs[path] = sha
    mapping = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                scope.model_dump(mode="json", include=_MAPPING_FIELDS, exclude_defaults=True),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if scope is not None
        else ""
    )
    background: dict[str, Any] = {"backend": report.backend}
    software = {"cheme-as-code": _minor("cheme-as-code")}
    if report.backend == "factors" and report.factors is not None and scope is not None:
        from chemeascode.domains.assessment.lca.backgrounds import DATA as PROFILES

        background["profiles"] = [
            {"id": name, "fingerprint": _sha(PROFILES, f"{name}.yaml")} for name in report.profiles
        ]
        background["sources"] = _manifest_sources(report)
    elif report.backend == "brightway" and scope is not None:
        from chemeascode.integrations import brightway as bw

        background["project"] = scope.brightway.project
        background["databases"] = report.databases
        background["methods"] = report.methods
        background["publication"] = scope.brightway.publication
        # the registry entries of referenced datasets (externally supplied amounts)
        background["sources"] = _manifest_sources(report)
        software.update(bw.versions())
    extra = {"water": report.water} if report.water is not None else {}
    if report.data_quality is not None:
        extra["data_quality"] = report.data_quality.as_dict()
    if report.pcf is not None:
        extra["pcf"] = {k: v for k, v in report.pcf.as_dict().items() if k != "background"}
    if report.balance is not None:
        extra["balance"] = report.balance.as_dict()
    return {
        "schema": MANIFEST_SCHEMA,
        "functional_unit": inv.functional_unit if inv else None,
        "case": inv.case if inv else None,
        "boundary": report.boundary,
        "allocation": inv.method if inv else None,
        "inputs": inputs,
        "results": "sha256:" + hashlib.sha256(results_csv(report).encode()).hexdigest(),
        "mapping": mapping,
        "background": background,
        "categories": [{"id": c.id, "unit": c.unit, "method": c.method} for c in report.categories],
        "settings": {
            "scenarios": list(report.scenarios),
            "uncertainty": (
                {"iterations": scope.uncertainty.iterations, "seed": scope.uncertainty.seed}
                if scope is not None and scope.uncertainty is not None
                else None
            ),
        },
        "software": software,
        "result": {
            "classification": report.classification,
            "label": report.label,
            "gaps": len(real_gaps([g for g in report.gaps if g.scenario == BASELINE])),
            "publication": report.publication,
            "publishable": report.publishable,
            "factors_published": not unpublished(report),
            "factor_status": factor_status(report),
        },
        **extra,
    }


def manifest_json(report: LcaReport) -> str:
    return json.dumps(manifest(report), indent=2) + "\n"


def outputs(report: LcaReport) -> dict[str, str]:
    """Every file ``cheme assess lca --write`` writes, by path (what the gate compares)."""
    found = {
        INVENTORY_CSV: inventory_csv(report),
        RESULTS_CSV: results_csv(report),
        RESULTS_MD: results_markdown(report),
        GAPS_CSV: gaps_csv(report),
        DATASET_FILE: dataset_yaml(report),
        MANIFEST_FILE: manifest_json(report),
    }
    if report.uncertainty is not None:
        found[UNCERTAINTY_CSV] = uncertainty_csv(report)
    return found


def dataset_yaml(report: LcaReport) -> str:
    """The plant's unallocated LCI dataset as ``lca/dataset.yaml`` (empty without one)."""
    dataset = report.inventory.dataset if report.inventory else None
    if dataset is None:
        return ""
    # sha256 of the text with normalised line endings: the same on every checkout
    files = {}
    for path in report.source.fingerprints:
        if path == FACTORS_FILE or not (report.root / path).is_file():
            continue
        content = (report.root / path).read_bytes().replace(b"\r\n", b"\n")
        files[path] = "sha256:" + hashlib.sha256(content).hexdigest()
    dataset = dataset.model_copy(
        update={"provenance": dataset.provenance.model_copy(update={"files": files})}
    )
    data = dataset.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
    # what the dataset is (scope, basis) is always stated, even at its default
    head = {
        "schema": dataset.schema_,
        "kind": dataset.kind,
        "id": dataset.id,
        "title": dataset.title,
        "description": dataset.description,
        "scope": dataset.scope,
        "basis": dataset.basis,
    }
    # then what the dataset is about, its documentation (v2), and its exchanges and provenance
    documented = [k for k in DatasetDocumentation.model_fields if k in data]
    tail = [k for k in ("sources", "exchanges", "allocation", "provenance") if k in data]
    order = [k for k in data if k not in head and k not in documented and k not in tail]
    data = {**head, **{k: data[k] for k in (*order, *documented, *tail)}}
    header = (
        "# The plant's unallocated LCI dataset (kind lci_dataset): generated by cheme assess\n"
        "# lca --write from the flowsheet and lca/lca.yaml; do not edit. Other studies reference\n"
        "# it as a background (dataset: {path, product, allocation}).\n"
    )
    return header + yaml.dump(
        data, Dumper=_DatasetDumper, sort_keys=False, allow_unicode=True, width=100
    )


class _DatasetDumper(yaml.SafeDumper):
    """Writes a list of numbers (pedigree scores) on one line."""


def _numbers(dumper: yaml.SafeDumper, data: list) -> yaml.Node:
    flow = bool(data) and all(isinstance(v, int | float) and not isinstance(v, bool) for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow or None)


_DatasetDumper.add_representer(list, _numbers)


def _construction_inputs(
    root: Path, scope: LcaFile
) -> tuple[list | None, list | None, list[Finding]]:
    """The take-off rows and equipment items the construction entries and the equipment-leak
    estimates count (None: absent), and the problems reading them. The equipment list is read
    whenever it is valid: the completeness of the emission estimates looks for combustion units
    and tanks in it."""
    kinds = {entry.takeoff for entry in scope.construction}
    if any(
        e.method == "equipment-leaks" and "mto" in e.count_from for e in scope.emission_estimates
    ):
        kinds.add("mto")
    takeoff = equipment = None
    found: list[Finding] = []
    if "mto" in kinds and (root / MTO_CSV).is_file():
        try:
            takeoff = read_takeoff((root / MTO_CSV).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, KeyError, ValueError) as failure:
            found.append(
                Finding(
                    MTO_CSV,
                    "error",
                    "cheme.lca-construction-input",
                    f"{MTO_CSV} cannot be read as a take-off: {failure!r}",
                    hint="rewrite it with cheme assess mto --write; never edit it by hand",
                )
            )
    parsed = Workspace(root).parsed_lists(("equipment",)).get("equipment")
    equipment = parsed.equipment if parsed is not None else None
    return takeoff, equipment, found


# -- formats ------------------------------------------------------------------------------------


def inventory_csv(report: LcaReport) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(INVENTORY_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in report.inventory.rows if report.inventory else []:
        writer.writerow(
            {
                "key": row.key,
                "title": row.title,
                "phase": row.phase,
                "direction": row.direction,
                "kind": row.kind,
                "plant": _g(row.plant),
                "plant_unit": row.plant_unit,
                "quantity": _g(row.quantity),
                "unit": row.unit,
                "provenance": row.provenance,
                "mapping": row.mapping,
                "streams": " ".join(row.streams),
            }
        )
    return buffer.getvalue()


def results_csv(report: LcaReport) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(RESULT_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for scenario in report.scenarios:
        totals = report.totals(scenario)
        for category in report.categories:
            total = totals[category.id]
            for impact in report.impacts:
                if impact.category != category.id or impact.scenario != scenario:
                    continue
                writer.writerow(
                    {
                        "scenario": scenario,
                        "category": category.id,
                        "category_unit": category.unit,
                        "key": impact.key,
                        "basis": impact.basis,
                        "quantity": _g(impact.quantity),
                        "unit": impact.unit,
                        "factor": _g(impact.factor),
                        "impact": _g(impact.value),
                        "share": f"{impact.value / total:.4f}" if total else "",
                        "phase": impact.phase,
                        "status": impact.status,
                        "source": impact.source,
                        "year": "" if impact.year is None else str(impact.year),
                    }
                )
            writer.writerow(
                {
                    "scenario": scenario,
                    "category": category.id,
                    "category_unit": category.unit,
                    "key": "total",
                    "impact": _g(total),
                    "share": "1.0000" if total else "",
                }
            )
    if report.pcf is not None:
        # the PCF breakdown: one row per line, category pcf, basis its
        # climate one
        for key, _, value, unit in report.pcf.lines():
            writer.writerow(
                {
                    "scenario": BASELINE,
                    "category": PCF_CATEGORY,
                    "category_unit": unit,
                    "key": key,
                    "basis": report.pcf.category,
                    "impact": _g(value),
                }
            )
    return buffer.getvalue()


#: The category of the PCF breakdown's rows in lca/results.csv.
PCF_CATEGORY = "pcf"


def _pcf_markdown(report: LcaReport) -> list[str]:
    """The PCF section of results.md: the breakdown, the study's choices and the carbon
    balance of the plant's dataset."""
    found = report.pcf
    carbon = report.inventory.carbon
    method = {
        "minus-one-plus-one": "-1/+1 (uptake -1, biogenic release +1)",
        "zero-zero": "0/0 (neither counted; the product's biogenic carbon declared)",
    }[found.biogenic_method]
    lines = [
        "",
        f"## Product carbon footprint per {found.functional_unit}",
        "",
        "ISO 14067 and the TfS PCF Guideline v3: emissions, removals and the product's carbon "
        f"content reported separately. From {found.category}, baseline.",
        "",
        f"- biogenic carbon: {method}; PCF stated: **{_g(found.headline)} kg CO2-eq** ("
        + ("including" if found.biogenic_method == "minus-one-plus-one" else "excluding")
        + " biogenic CO2)",
        f"- captured CO2 (CCU): {found.ccu_rule}; CO2 to storage (CCS): {found.ccs}",
        "- carbon content basis: physical (the carbon traced through the process; no "
        "mass-balance attribution); carbon from captured CO2 and direct air capture is "
        "reported separately below (TfS v3 5.2.10.4)",
        "",
        "| line | value | unit |",
        "|---|---|---|",
    ]
    lines += [f"| {label} | {_g(value)} | {unit} |" for _, label, value, unit in found.lines()]
    if found.background:
        lines += [
            "",
            "Background contributions count as fossil GHG emissions (their factors are taken "
            f"as excluding biogenic CO2): {', '.join(found.background)}.",
        ]
    for problem in found.problems:
        lines.append(f"**{problem}.**")
    lines += [
        "",
        f"Carbon balance of the dataset (kg C per {carbon.basis}): in {_g(carbon.total('in'))} "
        f"(biogenic {_g(carbon.total('in', True))}), out {_g(carbon.total('out'))} (biogenic "
        f"{_g(carbon.total('out', True))}), residual {_g(carbon.residual)}"
        + (
            f"; biogenic share of the pool {carbon.fraction:.1%}"
            if carbon.fraction is not None
            else ""
        )
        + ".",
    ]
    if carbon.unknown:
        lines.append(f"Carbon content unknown (not balanced): {', '.join(carbon.unknown)}.")
    if carbon.assumed_fossil:
        lines.append(
            "Counted as fossil (no biogenic fraction declared): "
            + ", ".join(carbon.assumed_fossil)
            + "."
        )
    return lines


def _boundary_lines(report: LcaReport) -> list[str]:
    """The section Boundary check of ``lca/results.md``: what the inventory leaves out."""
    gaps = report.boundary_check
    if gaps is None:
        return []
    lines = ["", "## Boundary check", "", *gaps.coverage_lines()]
    if gaps.unassigned_duties:
        lines += [
            "",
            "The inventory above excludes:",
            "",
            f"- the utilities (steam, cooling, refrigeration, power) of "
            f"{', '.join(gaps.unassigned_duties)}: no energy stream reaches them, so no exchange "
            "carries them",
        ]
    unclassified = [
        f.ids[0]
        for f in gaps.findings
        if f.rule == "cheme.boundary-unclassified" and f.level == "warning" and f.ids
    ]
    if unclassified:
        lines += [
            "",
            f"Not classified (no category): {', '.join(unclassified)}. Each is an exchange "
            "above, characterised by its mapping, but whether each is a product, wastewater, "
            "off-gas, solid waste or an emission is not stated in the flowsheet.",
        ]
    return lines + gaps.table_lines()


def results_markdown(report: LcaReport) -> str:
    inv = report.inventory
    if inv is None:
        return ""
    shares = ", ".join(f"{name} {share:.1%}" for name, share in inv.shares.items())
    order = ("operation", "construction", "maintenance", "transport", "end-of-life")
    present = list(dict.fromkeys(r.phase for r in inv.rows))
    phases = [p for p in order if p in present] + [p for p in present if p not in order]
    lines = [
        f"# LCA per {inv.functional_unit}",
        "",
        "Generated by `cheme assess lca --write` from lca/lca.yaml and its inputs; do not edit.",
        "",
        *(
            [
                "**Incomplete boundary: the boundary check found gaps; the inventory holds only "
                "the flowsheet's terminals (see the section Boundary check).**",
                "",
            ]
            if report.boundary_check is not None and not report.boundary_check.complete
            else []
        ),
        f"- case: {inv.case}; boundary: {report.boundary}; phases: {', '.join(phases)}",
        f"- allocation: {inv.method} ({shares})",
        f"- background: {report.background}"
        + (
            " -- **example factors (example: true): these numbers mean nothing**"
            if report.example
            else ""
        ),
        f"- result: **{report.label}**"
        + (f" ({'; '.join(report.reasons)})" if report.reasons else ""),
        f"- publication: {report.publication}"
        + (f" (by {', '.join(report.restricted_by)})" if report.restricted_by else "")
        + ("" if report.publishable else " -- **not for publication**"),
        "",
        "| category | unit | "
        + " | ".join(
            s + (" (with gaps)" if real_gaps([g for g in report.gaps if g.scenario == s]) else "")
            for s in report.scenarios
        )
        + " |",
        "|---|---|" + "---|" * len(report.scenarios),
    ]
    totals = {s: report.totals(s) for s in report.scenarios}
    standing = {s: report.comparability(s) for s in report.scenarios}
    verdicts = {s: scenario_verdict(report, s) for s in report.scenarios}

    def cell(scenario: str, category: str) -> str:
        if category not in standing[scenario]:
            value = _g(totals[scenario][category])
            if verdicts[scenario]["verdict"] == NOT_COMPARABLE:
                return f"{value} (not comparable)"
            return value
        lost = standing[scenario][category]
        if lost is None:
            return "no total (every contribution a gap)"
        return f"not comparable (no background for {', '.join(lost)})"

    for category in report.categories:
        values = " | ".join(cell(s, category.id) for s in report.scenarios)
        lines.append(f"| {category.title or category.id} | {category.unit} | {values} |")
    if len(report.scenarios) > 1:
        row = " | ".join(
            "reference" if s == BASELINE else f"**{verdicts[s]['verdict']}**"
            for s in report.scenarios
        )
        lines.append(f"| comparability with the baseline | | {row} |")
        lines += [
            "",
            "Comparability (structured factor scope, docs/framework/lci-comparison-basis.md):",
            "",
        ]
        for s in report.scenarios:
            if s != BASELINE:
                why = "; ".join(verdicts[s]["reasons"]) or (
                    "all compared dimensions declared and equal"
                    if verdicts[s]["compared"]
                    else "no background replaced"
                )
                spec = (
                    next((x for x in report.scope.scenarios if x.id == s), None)
                    if (report.scope)
                    else None
                )
                if spec is not None and spec.case:
                    why += f"; design case {spec.case}: the verdict covers the background only"
                lines.append(f"- {s}: {verdicts[s]['verdict']} ({why})")
    if len(phases) > 1:
        lines += ["", "By phase (baseline):", "", "| category | " + " | ".join(phases) + " |"]
        lines.append("|---|" + "---|" * len(phases))
        by_phase = {p: report.totals(BASELINE, p) for p in phases}
        for category in report.categories:
            values = " | ".join(_g(by_phase[p][category.id]) for p in phases)
            lines.append(f"| {category.title or category.id} | {values} |")
    if report.uncertainty is not None:
        mc = report.uncertainty
        lines += [
            "",
            f"## Uncertainty (baseline, Monte Carlo, {mc.iterations} iterations, seed {mc.seed})",
            "",
            "| category | deterministic | mean | median | 95 % interval | sd |",
            "|---|---|---|---|---|---|",
        ]
        titles = {c.id: f"{c.title or c.id} ({c.unit})" for c in report.categories}
        for s in mc.statistics:
            lines.append(
                f"| {titles.get(s.category, s.category)} | {_g4(s.deterministic)} | {_g4(s.mean)} "
                f"| {_g4(s.median)} | {_g4(s.low)} .. {_g4(s.high)} | {_g4(s.sd)} |"
            )
        for s in mc.statistics:
            if s.sensitivity:
                lines += [
                    "",
                    f"Sensitivity, {titles.get(s.category, s.category)} (Spearman rank "
                    "correlation with the total):",
                    "",
                ] + [f"- {name}: {rho:+.2f}" for name, rho in s.sensitivity]
    if len(report.comparison) > 1:
        lines += [
            "",
            "## Allocation (baseline)",
            "",
            "| method | share of "
            + inv.functional_unit.split(" ", 2)[-1]
            + " | "
            + " | ".join(f"{c.title or c.id} ({c.unit})" for c in report.categories)
            + " |",
            "|---|---|" + "---|" * len(report.categories),
        ]
        for entry in report.comparison:
            name = entry["method"] + (" (used)" if entry["current"] else "")
            if entry["totals"] is None:
                rest = "".join(" |" for _ in report.categories[1:])
                lines.append(f"| {name} | | not applicable: {entry['problem']} |{rest}")
                continue
            values = " | ".join(_g(entry["totals"][c.id]) for c in report.categories)
            lines.append(f"| {name} | {entry['share']:.1%} | {values} |")
    if report.pcf is not None:
        lines += _pcf_markdown(report)
    for category in report.categories:
        total = totals[BASELINE][category.id]
        unit = category.unit + (f", {category.method}" if category.method else "")
        lines += [
            "",
            f"## {category.title or category.id} ({unit}), baseline",
            "",
            "| flow | quantity | factor | impact | share |",
            "|---|---|---|---|---|",
        ]
        rows = sorted(
            (i for i in report.impacts if i.category == category.id and i.scenario == BASELINE),
            key=lambda i: -abs(i.value),
        )
        for impact in rows:
            share = f"{impact.value / total:.1%}" if total else ""
            lines.append(
                f"| {impact.key} | {_g(impact.quantity)} {impact.unit} | {_g(impact.factor)} "
                f"/{impact.unit} ({impact.basis}) | {_g(impact.value)} | {share} |"
            )
    free = [row.key for row in inv.rows if row.mapping == "free"]
    unmapped = [row.key for row in inv.rows if not row.mapping]
    lines += [
        "",
        "## Inventory",
        "",
        "| flow | phase | per functional unit | provenance | background |",
        "|---|---|---|---|---|",
    ]
    for row in inv.rows:
        lines.append(
            f"| {row.key} ({row.direction}) | {row.phase} | {_g(row.quantity)} {row.unit} | "
            f"{row.provenance} | {row.mapping or 'UNMAPPED'} |"
        )
    lines += ["", "Co-products are listed with what is made alongside one functional unit."]
    if free:
        lines.append(f"Without burden (free): {', '.join(free)}.")
    if unmapped:
        lines.append(f"**Not characterised (unmapped): {', '.join(unmapped)}.**")
    baseline = [g for g in report.gaps if g.scenario == BASELINE]
    gaps = real_gaps(baseline)
    outside = [g for g in baseline if g not in gaps]
    if gaps:
        lines += [
            "",
            "## Gaps (baseline)",
            "",
            "These exchanges have no burden in the category: the totals exclude them (they are "
            "not counted as 0). How much they would add is unknown; no coverage percentage is "
            "given, because there is no defensible denominator. lca/gaps.csv lists every "
            "scenario.",
            "",
            "| category | flow | quantity | why |",
            "|---|---|---|---|",
        ]
        for gap in gaps:
            why = GAP_REASONS.get(gap.reason, gap.reason) + (
                f" ({gap.detail})" if gap.detail else ""
            )
            amount = "unknown" if gap.quantity is None else f"{_g(gap.quantity)} {gap.unit}"
            lines.append(f"| {gap.category} | {gap.key} | {amount} | {why} |")
    if outside:
        lines += [
            "",
            "## Outside the methods (baseline)",
            "",
            "Elementary flows a method does not list contribute nothing to that category by the "
            "method's definition; they are no gaps.",
            "",
            "| category | flow | quantity | method |",
            "|---|---|---|---|",
        ] + [
            f"| {g.category} | {g.key} | {_g(g.quantity)} {g.unit} | {g.detail} |" for g in outside
        ]
    lines += _boundary_lines(report)
    if report.sources:
        lines += [
            "",
            "## Sources",
            "",
            "| source | version | licence | publication |",
            "|---|---|---|---|",
        ]
        for s in report.sources:
            lines.append(
                f"| {s.title} ({s.provider}) | {s.version} | {s.licence} | {s.publication} |"
            )
        attributions = [s.attribution for s in report.sources if s.attribution]
        if attributions:
            lines += [""] + attributions
    if report.limitations:
        lines += ["", "## Limitations", ""] + [f"- {item}" for item in report.limitations]
    return "\n".join(lines) + "\n"
