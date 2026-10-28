"""Stage gates on the LCA: ``kind: lca`` in ``checks/checks.yaml``.

Each item of the gate's ``require`` is one test:

- ``mapped``: ``lca/lca.yaml`` gives every flow of the inventory a background (a factor, an
  activity or biosphere flow, free, or an emission whose components are mapped);
- ``factors``: backend factors: ``lca/factors.yaml`` is not an example (that it has every mapped
  factor is part of computing at all); backend brightway: nothing more to check;
- ``no-gaps``: no exchange lacks a burden in a category, in the baseline or a scenario
  (``lca/gaps.csv`` lists none but flows outside a method's scope): the result is not partial;
- ``factors-published``: every exchange of the baseline and every scenario rests on published
  data (pre-release issue 322): its factor status (:func:`.report.factor_status`) is ``PUBLISHED``,
  ``EPD``, a background database's (``database``) or no burden by declaration (``none``); an example
  factor, an ``ASSUMED``, ``PROXY`` or ``ESTIMATE`` one, or a gap fails it and is named;
- ``publishable``: the results may be published: every source they draw on is ``public``, or
  ``restricted`` with the study's reviewed ``publication:`` decision (never ``local``);
- ``lci-documented``: the plant's LCI dataset (``lca/dataset.yaml``) gives the publication
  minimum of its documentation (:data:`.documentation.PUBLICATION_MINIMUM`: uuid, version,
  geography with its description, reference year and validity, technology and its level,
  boundary, ISIC and CPC, modelling principle and multi-functionality, a review record, possibly
  ``type: none``, rights and data generator);
- ``cutoff-criteria``: the plant's LCI dataset meets the cut-off criteria and its system model
  (:mod:`.cutoff`, pre-release issue 180): every recorded cut flow below 1 % of the input mass, all
  of them together below 1 %, none on the never-cut list, no avoided-burden credit in a
  non-crediting system model (an ``avoided:`` input, a negative end-of-life or recyclable output, or
  allocation by substitution), and every consumable replaced or charged with a disposal output or a
  recorded cut-off (infos, such as a cut flow with no amount in kg, do not fail it);
- ``lci-emissions-complete``: no emission source the flowsheet does not carry is left without
  an estimate or a declared exclusion (pre-release issue 176, :mod:`.emissions`): a combustion unit
  or fuel feed, a flare, a storage tank or a wastewater outlet not sent to a treatment background
  (the warning ``cheme.lci-emissions-incomplete``);
- ``lci-mass-balance``, ``lci-element-balance``, ``lci-carbon-origin``: the plant's LCI
  dataset closes (:mod:`.balance`, pre-release issue 174) in total mass (free resources such as air
  and water included), in each element (C, H, O, N, S, Cl, ... from the exchanges' compositions),
  and in carbon by origin (the fossil, biogenic and atmospheric carbon of the inputs against the
  products, emissions and wastes; no output declared fossil or biogenic carrying more carbon of
  that origin than the inputs give), within the default tolerance (1 % for a dataset from a
  simulated flowsheet, 5 % for a sourced screening one). A balance that cannot be assessed (a
  material exchange without a composition) fails too: exclude the exchange with its reason
  (``balance_exclusion``) or give its composition. Each problem names its residual;
- ``lca-current``: every file ``cheme assess lca --write`` writes (``lca/inventory.csv``,
  ``results.csv``, ``results.md``, ``gaps.csv``, ``dataset.yaml``, ``manifest.json``,
  ``uncertainty.csv``) exists
  and is what ``cheme assess lca`` gives now.

An LCA that does not compute (an input that does not load, an error of the inventory or the
characterisation) fails every requirement.

The checks are structural: whether the scope, the mapping and the factors are *right* is the
judgement of the LCA's review.
"""

from __future__ import annotations

from pathlib import Path

from chemeascode.domains.assessment.lca.cutoff import findings as cutoff_findings
from chemeascode.domains.assessment.lca.documentation import missing as undocumented
from chemeascode.domains.assessment.lca.emissions import RULE_INCOMPLETE
from chemeascode.domains.assessment.lca.impacts import real_gaps
from chemeascode.domains.assessment.lca.report import lca_report, outputs, unpublished

REQUIREMENTS = (
    "mapped",
    "factors",
    "no-gaps",
    "factors-published",
    "publishable",
    "lci-documented",
    "cutoff-criteria",
    "lci-emissions-complete",
    "lci-mass-balance",
    "lci-element-balance",
    "lci-carbon-origin",
    "lca-current",
)
#: The requirements the plant dataset's balance decides (:mod:`.balance`).
BALANCE_REQUIREMENTS = ("lci-mass-balance", "lci-element-balance", "lci-carbon-origin")
#: The findings ``cutoff-criteria`` fails on.
CUTOFF_RULES = (
    "cheme.lca-cutoff-share",
    "cheme.lca-cutoff-sum",
    "cheme.lca-cutoff-never",
    "cheme.lca-cutoff-credit",
    "cheme.lca-system-model-mixed",
    "cheme.lca-system-model",
    "cheme.lca-byproduct-free",
    "cheme.lca-disposal",
)


def _read(root: Path, name: str) -> str | None:
    path = root / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def lca_gate(root: Path, require: list[str]) -> list[str]:
    """What fails of *require* for the repository at *root*; empty when the gate passes."""
    root = Path(root)
    report = lca_report(root)
    if not report.loaded:
        errors = [f for f in report.findings if f.level == "error"]
        return [errors[0].message if errors else "the LCA does not load"]
    problems: list[str] = []
    if "mapped" in require:
        unmapped = [row.key for row in report.inventory.rows if not row.mapping]
        if unmapped:
            problems.append(f"flows without background in lca/lca.yaml: {', '.join(unmapped)}")
    if "factors" in require and report.example:
        problems.append("lca/factors.yaml is an example (example: true); use the project's")
    if "no-gaps" in require and real_gaps(report.gaps):
        keys = sorted({g.key for g in real_gaps(report.gaps)})
        problems.append(
            f"{len(keys)} exchanges lack a burden in some category (lca/gaps.csv): "
            + ", ".join(keys[:5])
            + (" ..." if len(keys) > 5 else "")
        )
    if "factors-published" in require:
        found = unpublished(report)
        if found:
            problems.append(
                f"{len(found)} exchanges rest on unpublished factors: "
                + ", ".join(found[:5])
                + (" ..." if len(found) > 5 else "")
            )
    if "publishable" in require and not report.publishable:
        problems.append(
            f"the results draw on {report.publication} sources ("
            + ", ".join(report.restricted_by)
            + (
                "): local sources are never published"
                if report.publication == "local"
                else "): not publishable without a reviewed publication: decision in lca/lca.yaml"
            )
        )
    if "lci-documented" in require:
        dataset = report.inventory.dataset
        lacking = undocumented(dataset) if dataset is not None else ["the dataset itself"]
        if lacking:
            problems.append(
                "lca/dataset.yaml lacks the publication minimum: "
                + ", ".join(lacking)
                + " (dataset: in lca/lca.yaml)"
            )
    if "cutoff-criteria" in require:
        dataset = report.inventory.dataset
        found = cutoff_findings(dataset, "lca/dataset.yaml") if dataset is not None else []
        failing = [
            f for f in found + report.findings if f.rule in CUTOFF_RULES and f.level != "info"
        ]
        problems += list(dict.fromkeys(f.message for f in failing))
    if "lci-emissions-complete" in require:
        problems += list(
            dict.fromkeys(f.message for f in report.findings if f.rule == RULE_INCOMPLETE)
        )
    for requirement in BALANCE_REQUIREMENTS:
        if requirement not in require:
            continue
        if report.balance is None:
            problems.append(f"{requirement}: no LCI dataset to balance (lca/dataset.yaml)")
            continue
        _, found = report.balance.status(requirement)
        problems += [f"lca/dataset.yaml: {p}" for p in found]
    if "lca-current" in require:
        for name, text in outputs(report).items():
            committed = _read(root, name)
            if committed is None:
                problems.append(f"no {name}; run cheme assess lca --write")
            elif committed != text:
                problems.append(f"{name} is not current; run cheme assess lca --write")
    return problems
