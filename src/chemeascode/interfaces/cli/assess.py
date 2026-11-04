"""``cheme assess``: the material take-off, the estimates, the LCA and the TEA of the plant."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

assess_app = typer.Typer(
    help="Assessment: the material take-off of the 3D model, the estimates, the LCA and the TEA.",
    no_args_is_help=True,
)


def _workspace() -> Workspace:
    from chemeascode.foundation.workspace import check_requirement

    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    check_requirement(workspace.root)
    return workspace


def _write_or_check(
    workspace: Workspace, outputs: dict[str, str], write: bool, check: bool, command: str
) -> bool:
    """Write the *outputs* (path -> text) or compare them with the files; True when handled."""
    if write:
        for name, text in outputs.items():
            path = workspace.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            typer.echo(f"wrote {name}")
        return True
    if check:
        stale = [
            name
            for name, text in outputs.items()
            if not (workspace.root / name).is_file()
            or (workspace.root / name).read_text(encoding="utf-8") != text
        ]
        for name in stale:
            typer.echo(f"{name} is not current; run cheme assess {command} --write")
        if stale:
            raise typer.Exit(1)
        typer.echo(", ".join(outputs) + " current")
        return True
    return False


@assess_app.command("mto")
def mto(
    csv: Annotated[bool, typer.Option("--csv", help="CSV, one row per quantity.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Rows, totals, findings and provenance as JSON.")
    ] = False,
    write: Annotated[
        bool, typer.Option("--write", help="Write estimate/mto.csv and estimate/mto.md.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when estimate/mto.csv or .md is not current.")
    ] = False,
) -> None:
    """The material take-off of layout/plant-model.yaml (Markdown by default): pipe by DN, class
    and insulation; elbows, tees, reducers, flanges; valves; steel tonnage; grating, insulation
    and concrete."""
    from chemeascode.domains.assessment.mto import (
        MTO_CSV,
        MTO_MD,
        mto_csv,
        mto_markdown,
        mto_report,
    )

    workspace = _workspace()
    report = mto_report(workspace.root)
    for finding in report.findings:
        typer.echo(finding.format(), err=True)
    if not report.loaded:
        raise typer.Exit(1)
    outputs = {MTO_CSV: mto_csv(report.rows), MTO_MD: mto_markdown(report.takeoff)}
    if _write_or_check(workspace, outputs, write, check, "mto"):
        return
    if as_json:
        typer.echo(report.to_json())
    elif csv:
        typer.echo(outputs[MTO_CSV], nl=False)
    else:
        typer.echo(outputs[MTO_MD], nl=False)


@assess_app.command("estimate")
def estimate(
    csv: Annotated[bool, typer.Option("--csv", help="CSV, one line per row and factor.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Lines, totals, findings and provenance as JSON.")
    ] = False,
    write: Annotated[
        bool,
        typer.Option("--write", help="Write estimate/estimate.csv and estimate/estimate.md."),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="Exit 1 when estimate/estimate.csv or .md is not current."),
    ] = False,
) -> None:
    """The take-off priced with estimate/rates.yaml, then its factors (direct, indirect,
    contingency): Markdown by default. cheme holds no prices; every rate is the project's,
    with its status, source and year."""
    from chemeascode.domains.assessment.estimate import (
        ESTIMATE_CSV,
        ESTIMATE_MD,
        estimate_csv,
        estimate_markdown,
        estimate_report,
    )

    workspace = _workspace()
    report = estimate_report(workspace.root)
    for finding in report.findings:
        typer.echo(finding.format(), err=True)
    if not report.loaded:
        raise typer.Exit(1)
    result = report.estimate
    outputs = {ESTIMATE_CSV: estimate_csv(result), ESTIMATE_MD: estimate_markdown(result)}
    if _write_or_check(workspace, outputs, write, check, "estimate"):
        return
    if as_json:
        typer.echo(report.to_json())
    elif csv:
        typer.echo(outputs[ESTIMATE_CSV], nl=False)
    else:
        typer.echo(outputs[ESTIMATE_MD], nl=False)


@assess_app.command("equipment")
def equipment(
    csv: Annotated[bool, typer.Option("--csv", help="CSV, one line per item.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Lines, totals, findings and provenance as JSON.")
    ] = False,
    write: Annotated[
        bool,
        typer.Option(
            "--write", help="Write estimate/equipment-cost.csv and estimate/equipment-cost.md."
        ),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="Exit 1 when estimate/equipment-cost.csv or .md is stale."),
    ] = False,
) -> None:
    """The equipment estimate from published cost correlations (Turton et al., CAPCOST): the
    purchased and bare module cost of every listed item, escalated by the project's cost
    index in estimate/cost-basis.yaml (Markdown by default)."""
    from chemeascode.domains.assessment.equipment_cost import (
        COST_CSV,
        COST_MD,
        cost_csv,
        cost_markdown,
        equipment_estimate,
    )

    workspace = _workspace()
    result = equipment_estimate(workspace.root)
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if any(f.level == "error" for f in result.findings):
        raise typer.Exit(1)
    outputs = {COST_CSV: cost_csv(result), COST_MD: cost_markdown(result)}
    if _write_or_check(workspace, outputs, write, check, "equipment"):
        return
    if as_json:
        typer.echo(result.to_json())
    elif csv:
        typer.echo(outputs[COST_CSV], nl=False)
    else:
        typer.echo(outputs[COST_MD], nl=False)


@assess_app.command("lca")
def lca(
    csv: Annotated[
        bool, typer.Option("--csv", help="The impacts as CSV, one row per contributor.")
    ] = False,
    inventory: Annotated[
        bool, typer.Option("--inventory", help="The foreground inventory as CSV.")
    ] = False,
    dataset: Annotated[
        bool,
        typer.Option("--dataset", help="The unallocated LCI dataset (kind lci_dataset) as YAML."),
    ] = False,
    coverage: Annotated[
        bool,
        typer.Option(
            "--coverage",
            help="How far the result can be read: the classification and its reasons, the "
            "gaps (exchanges without a burden), the sources, the limitations, the data quality "
            "rating (TfS DQR, PEF-style indicators, primary data share) and the water balance. "
            "Writes nothing.",
        ),
    ] = False,
    balance: Annotated[
        bool,
        typer.Option(
            "--balance",
            help="The mass, element (C, H, O, N, S, Cl, ...) and carbon-by-origin balance of "
            "the plant's LCI dataset and its energy closure: in, out and residual per quantity "
            "(kg per hour and %), the tolerance, and the exchanges excluded with their reasons "
            "(with --json: as JSON). Needs no factors or background. Writes nothing.",
        ),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Inventory, impacts, findings and provenance as JSON.")
    ] = False,
    write: Annotated[
        bool,
        typer.Option(
            "--write",
            help="Write lca/inventory.csv, results.csv, results.md, gaps.csv, the "
            "unallocated LCI dataset lca/dataset.yaml and the run manifest lca/manifest.json.",
        ),
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when one of the lca/ outputs is not current.")
    ] = False,
    pact: Annotated[
        Path | None,
        typer.Option(
            "--pact",
            help="Write the product carbon footprint as a WBCSD PACT (Pathfinder) v2 "
            "ProductFootprint JSON to this file (needs carbon_accounting with pact: in "
            "lca/lca.yaml).",
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Exit 1 when an exchange of the baseline or a scenario rests on an unpublished "
            "factor: an example factor, one ASSUMED, PROXY or ESTIMATE, or a gap (each named "
            "as the error cheme.lca-factor-status, with its factor status).",
        ),
    ] = False,
    case: Annotated[
        str | None,
        typer.Option(
            "--case",
            help="With --dataset, --write or --check only: the unallocated LCI dataset of this "
            "flowsheet case instead of lca/lca.yaml's, its id, title and uuid naming the case; "
            "--write writes it to lca/datasets/<dataset id>-<case>.yaml, --check exits 1 when "
            "that file is stale. The case lca/lca.yaml studies is the same as no --case.",
        ),
    ] = None,
) -> None:
    """The LCA of the plant's operation per functional unit (Markdown by default): the
    flowsheet's feeds and products in the case of lca/lca.yaml, shared between the co-products,
    characterised with lca/factors.yaml (and the open profiles it includes) or a Brightway
    project. --inventory and --dataset alone need neither: the foreground is exported without a
    background database or credentials. Every exchange without a burden is a gap, never 0."""
    from chemeascode.domains.assessment.lca.report import LCA_FILE, unpublished
    from chemeascode.foundation.findings import Finding

    if case is not None:
        others = csv or inventory or coverage or balance or as_json or strict or pact is not None
        if others or not (dataset or write or check):
            typer.echo("--case goes with --dataset, --write or --check only", err=True)
            raise typer.Exit(2)
        if _lca_case(case, write, check):
            return
    report = _lca(csv, inventory, dataset, coverage, balance, as_json, write, check, pact, strict)
    if not strict:
        return
    problems = unpublished(report)
    for problem in problems:
        finding = Finding(
            LCA_FILE,
            "error",
            "cheme.lca-factor-status",
            f"--strict: {problem}",
            hint="characterise it with a published factor or background (lca/factors.yaml, "
            "lca/lca.yaml), or leave --strict off for a screening result",
            key=problem,
        )
        typer.echo(finding.format(), err=True)
    if problems:
        raise typer.Exit(1)


def _lca_case(case: str, write: bool, check: bool) -> bool:
    """``cheme assess lca --dataset|--write|--check --case``: the dataset of flowsheet *case*.
    False when *case* is the one lca/lca.yaml studies (the command then runs as without it)."""
    from chemeascode.domains.assessment.lca.case_dataset import (
        UnknownCase,
        case_dataset,
        overwrite_finding,
        stale_finding,
        variant_case,
    )

    workspace = _workspace()
    try:
        if variant_case(workspace.root, case) is None:
            return False
        result = case_dataset(workspace.root, case)
    except UnknownCase as failure:
        declared = ", ".join(failure.cases) if failure.cases else "none declared"
        typer.echo(f"unknown case {case}; cases of process/flowsheet.yaml: {declared}", err=True)
        raise typer.Exit(2) from failure
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if not result.loaded:
        typer.echo(f"no LCI dataset for case {case}", err=True)
        raise typer.Exit(1)
    if write:
        refused = overwrite_finding(workspace.root, result)
        if refused is not None:
            typer.echo(refused.format(), err=True)
            raise typer.Exit(1)
        path = workspace.root / result.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.text, encoding="utf-8")
        typer.echo(f"wrote {result.path}")
    elif check:
        stale = stale_finding(workspace.root, result)
        if stale is not None:
            typer.echo(stale.format(), err=True)
            raise typer.Exit(1)
        typer.echo(f"{result.path} current")
    else:
        typer.echo(result.text, nl=False)
    return True


def _lca(
    csv: bool,
    inventory: bool,
    dataset: bool,
    coverage: bool,
    balance: bool,
    as_json: bool,
    write: bool,
    check: bool,
    pact: Path | None,
    strict: bool,
):
    """The work of ``cheme assess lca`` (its report, for --strict)."""
    from chemeascode.domains.assessment.lca.report import (
        DATASET_FILE,
        GAP_REASONS,
        INVENTORY_CSV,
        RESULTS_CSV,
        RESULTS_MD,
        dataset_yaml,
        inventory_csv,
        lca_report,
        outputs,
    )

    workspace = _workspace()
    foreground = (inventory or dataset) and not (
        write or check or as_json or csv or coverage or pact or balance
    )
    balance_only = balance and not (
        write or check or csv or coverage or pact or inventory or dataset
    )
    # --strict needs the characterised result, whatever is shown
    report = lca_report(
        workspace.root, inventory_only=bool((foreground or balance_only) and not strict)
    )
    for finding in report.findings:
        typer.echo(finding.format(), err=True)
    if not report.loaded:
        raise typer.Exit(1)
    if balance_only:
        import json

        from chemeascode.domains.assessment.lca.balance import text as balance_text

        if report.balance is None:
            typer.echo("no LCI dataset to balance", err=True)
            raise typer.Exit(1)
        typer.echo(
            json.dumps(report.balance.as_dict(), indent=2)
            if as_json
            else balance_text(report.balance),
            nl=as_json,
        )
        return report
    if foreground:
        typer.echo(dataset_yaml(report) if dataset else inventory_csv(report), nl=False)
        return report
    if pact is not None:
        import datetime as dt

        from chemeascode.domains.assessment.lca.pact import footprint, footprint_json

        document, problems = footprint(report, dt.datetime.now(dt.UTC))
        for problem in problems:
            typer.echo(f"lca/lca.yaml: error: cheme.lca-pact: {problem}", err=True)
        if document is None:
            raise typer.Exit(1)
        pact.write_text(footprint_json(document), encoding="utf-8")
        typer.echo(f"wrote {pact}", err=True)
        if not (write or check or as_json or csv or coverage or inventory or dataset):
            return report
    files = outputs(report)
    if check and not write and files.get(DATASET_FILE):
        from chemeascode.domains.assessment.lca.case_dataset import CaseDataset, stale_finding

        # the dataset's staleness as the finding --check --case reports for a case dataset
        study = report.inventory.case if report.inventory is not None else ""
        stale = stale_finding(
            workspace.root, CaseDataset(study or "", DATASET_FILE, files[DATASET_FILE], report)
        )
        if stale is not None:
            typer.echo(stale.format(), err=True)
    if _write_or_check(workspace, files, write, check, "lca"):
        return report
    if coverage:
        typer.echo(f"result: {report.label}")
        for reason in report.reasons:
            typer.echo(f"  - {reason}")
        baseline = [g for g in report.gaps if g.scenario == "baseline"]
        typer.echo(f"gaps (baseline): {len(baseline)}")
        for gap in baseline:
            typer.echo(
                f"  {gap.category}: {gap.key} "
                + ("(amount unknown)" if gap.quantity is None else f"{gap.quantity:.6g} {gap.unit}")
                + ": "
                f"{GAP_REASONS.get(gap.reason, gap.reason)}"
                + (f" ({gap.detail})" if gap.detail else "")
            )
        for source in report.sources:
            typer.echo(
                f"source: {source.id} ({source.provider}, {source.version}, {source.licence}, "
                f"publication {source.publication})"
            )
        for item in report.limitations:
            typer.echo(f"limitation: {item}")
        if report.boundary_check is not None:
            b = report.boundary_check
            warned = sorted({f.rule for f in b.findings if f.level in ("warning", "error")})
            typer.echo(
                "boundary check: "
                + (f"gaps ({', '.join(warned)})" if warned else "no gap found by its rules")
                + (
                    f"; utilities in no exchange: {', '.join(b.unassigned_duties)}"
                    if b.unassigned_duties
                    else ""
                )
            )
        if report.data_quality is not None:
            q = report.data_quality
            typer.echo(
                f"data quality ({q.basis}, {q.exchanges} exchanges): DQR {q.dqr:.2f} (TfS: TeR "
                f"{q.TeR:.2f}, GeR {q.GeR:.2f}, TiR {q.TiR:.2f}); PEF-style DQR {q.dqr_pef:.2f} "
                f"(P {q.P:.2f}, C {q.C:.2f}); primary data share {q.primary_share:.0%}; "
                f"weakest: {q.weakest}" + ("" if q.weighted else " (unweighted: a simplification)")
            )
        if report.balance is not None:
            from chemeascode.domains.assessment.lca.balance import summary

            typer.echo(summary(report.balance))
        if report.water is not None:
            w = report.water
            typer.echo(
                f"water (m3 per {w['basis']}): withdrawal {w['withdrawal']:.6g}, returned "
                f"{w['returned']:.6g}, evaporated {w['evaporated']:.6g}, consumption "
                f"{w['consumption']:.6g}"
            )
        typer.echo(
            f"publication: {report.publication}"
            + (f" (by {', '.join(report.restricted_by)})" if report.restricted_by else "")
            + ("; publishable" if report.publishable else "; not publishable")
        )
        return report
    if as_json:
        typer.echo(report.to_json())
    elif inventory:
        typer.echo(files[INVENTORY_CSV], nl=False)
    elif dataset:
        typer.echo(files[DATASET_FILE], nl=False)
    elif csv:
        typer.echo(files[RESULTS_CSV], nl=False)
    else:
        typer.echo(files[RESULTS_MD], nl=False)
    return report


@assess_app.command("lca-scenarios")
def lca_scenarios(
    ids: Annotated[
        list[str] | None,
        typer.Argument(help="Scenario ids of lca/lca.yaml (baseline included); default: all."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="The records as one JSON object, by path.")
    ] = False,
    write: Annotated[
        bool, typer.Option("--write", help="Write lca/scenarios/<id>.json, one per scenario.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when a scenario record is not current.")
    ] = False,
) -> None:
    """One machine-readable record per LCA scenario (a summary by default): its stable id
    <dataset>/<case>/<scenario>, the design case, the unallocated foreground, each exchange's
    background in the scenario (geography, year, status, source; linked, proxy, missing), the
    characterised totals per functional unit with the allocation, the gaps, warnings,
    publication policy and input fingerprints. A regional scenario changes the background only;
    only a scenario naming its own flowsheet case changes the foreground."""
    import json
    from fnmatch import fnmatchcase

    from chemeascode.domains.assessment.lca.report import lca_report
    from chemeascode.domains.assessment.lca.scenarios import records

    workspace = _workspace()
    report = lca_report(workspace.root)
    for finding in report.findings:
        typer.echo(finding.format(), err=True)
    if not report.loaded:
        raise typer.Exit(1)
    try:
        files = records(report, ids or None)
    except KeyError as failure:
        typer.echo(
            f"unknown scenario {failure.args[0]}; scenarios: {', '.join(report.scenarios)}",
            err=True,
        )
        raise typer.Exit(2) from failure
    from chemeascode.domains.assessment.lca.scenarios import SCENARIO_DIR

    # records of scenarios no longer in lca/lca.yaml: never left to be published as current
    orphans = (
        sorted(
            f"{SCENARIO_DIR}/{p.name}"
            for p in (workspace.root / SCENARIO_DIR).glob("*.json")
            if f"{SCENARIO_DIR}/{p.name}" not in files
        )
        if not ids
        else []
    )
    if check and orphans:
        for name in orphans:
            typer.echo(
                f"{name} is no scenario of lca/lca.yaml; run cheme assess lca-scenarios --write"
            )
        raise typer.Exit(1)
    if write:
        for name in orphans:
            (workspace.root / name).unlink()
            typer.echo(f"removed {name} (no scenario of lca/lca.yaml)")
    if _write_or_check(workspace, files, write, check, "lca-scenarios"):
        return
    if as_json:
        typer.echo(json.dumps({p: json.loads(t) for p, t in files.items()}, indent=2))
        return
    for path, text in files.items():
        data = json.loads(text)
        scenario, impacts = data["scenario"], data["impacts"]
        totals = ", ".join(
            f"{c['id']} "
            + (
                "not computable (gaps)"
                if impacts["totals"][c["id"]] is None
                else f"{impacts['totals'][c['id']]:.6g} {c['unit']}"
            )
            for c in impacts["categories"]
        )
        typer.echo(
            f"{data['id']} ({scenario['kind']}, foreground {data['foreground']['relation']}): "
            f"{scenario['location'] or 'no geography'} {scenario['year'] or ''}".rstrip()
        )
        fu = impacts["functional_unit"]
        typer.echo(
            f"  per {fu['amount']:g} {fu['unit']} {fu['product']} "
            f"({impacts['allocation']['method']} allocation): {totals}; "
            f"{impacts['classification']}"
        )
        links = data["linked_inventory"]["exchanges"]
        states: dict[str, int] = {}
        for link in links:
            states[link["state"]] = states.get(link["state"], 0) + 1
        typer.echo("  exchanges: " + ", ".join(f"{n} {s}" for s, n in sorted(states.items())))
        if impacts["dropped"]:
            typer.echo(
                "  NOT COMPARABLE with the baseline: no background here for "
                + ", ".join(impacts["dropped"])
            )
        declared = [*scenario["missing"], *scenario["proxy"]]
        for link in links:
            # what the scenario changes against the baseline; the baseline's own proxies
            shown = (
                link["replaced"]
                or link["state"] in ("unmapped", "gap")
                or any(fnmatchcase(link["key"], pattern) for pattern in declared)
                or (scenario["kind"] == "baseline" and link["state"] == "proxy")
            )
            if shown:
                typer.echo(
                    f"  {link['key']}: {link['state']} {link['background'] or ''}"
                    + (f" [{link['location']}]" if link["location"] else "")
                    + (f" ({link['note']})" if link["note"] else "")
                )
        for note in data["notes"]:
            typer.echo(f"  note: {note}")
        publication = data["publication"]
        typer.echo(
            f"  publication: {publication['policy']}"
            + ("" if publication["publishable"] else " (not publishable)")
            + f"; {path}"
        )


@assess_app.command("lca-cases")
def lca_cases(
    cases: Annotated[
        list[str] | None, typer.Argument(help="Flowsheet case ids; default: every case.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="The comparison as JSON.")] = False,
) -> None:
    """Existing flowsheet cases side by side: each case's declared capacity and provenance, and
    each exchange per unit (kg, or kWh for an energy product) of the functional unit's product
    (unallocated). Only computed cases;
    nothing is scaled, and an exchange a case lacks is shown as missing, not 0."""
    import json

    from chemeascode.domains.assessment.lca.scenarios import compare_cases

    workspace = _workspace()
    rows, findings = compare_cases(workspace.root, cases or None)
    for finding in findings:
        typer.echo(finding.format(), err=True)
    if any(f.level == "error" for f in findings):
        raise typer.Exit(1)
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for row in rows:
        product = row["product"] or {}
        typer.echo(
            f"case {row['case']}: capacity {row['capacity'] or 'not declared'}, provenance "
            f"{row['provenance'] or 'not declared'}"
            + (" (EXTRAPOLATED: not predictive)" if row["extrapolated"] else "")
            + (
                f"; {product['key']} "
                + (
                    "missing"
                    if product["amount"] is None
                    else f"{product['amount']:g} {product['unit']}"
                )
                if product
                else ""
            )
        )
        for key, value in row["per_unit"].items():
            shown = "missing" if value is None else f"{value['amount']:.6g} {value['unit']}"
            typer.echo(f"  {key}: {shown}")
        for key in row["unknown"]:
            typer.echo(f"  {key}: amount unknown (missing)")


@assess_app.command("lci-estimate")
def lci_estimate(
    spec: Annotated[
        str, typer.Argument(help="The estimate (kind lci_estimate), from the repository root.")
    ] = "lca/estimate.yaml",
    write: Annotated[
        bool,
        typer.Option("--write", help="Write the dataset (default lca/datasets/<id>.yaml)."),
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when the written dataset is not current.")
    ] = False,
    compare: Annotated[
        bool,
        typer.Option(
            "--compare",
            help="Compare the estimate with the repository's flowsheet (process/flowsheet.yaml), "
            "per kg of the product: the validation of a tier against a full design.",
        ),
    ] = False,
    case: Annotated[
        str | None, typer.Option("--case", help="The flowsheet case for --compare.")
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="The dataset, its balance and the findings as JSON.")
    ] = False,
) -> None:
    """A Tier 0 (stoichiometric) or Tier 1 (sourced conceptual) LCI dataset for a process
    without a flowsheet (YAML by default): from the reactions of process/reactions.yaml, the
    formulas of process/materials.yaml and the estimate's yield and selectivity, with every
    default exchange marked assumed and its rule cited. Refuses a dataset whose element balance
    does not close."""
    from chemeascode.domains.assessment.lca.estimate import (
        compare_with_design,
        estimate_yaml,
    )
    from chemeascode.domains.assessment.lca.estimate import lci_estimate as estimate

    workspace = _workspace()
    result = estimate(workspace.root, spec)
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if not result.loaded:
        raise typer.Exit(1)
    text = estimate_yaml(result)
    if _write_or_check(workspace, {result.output: text}, write, check, "lci-estimate"):
        return
    if compare:
        try:
            comparison = compare_with_design(result.dataset, workspace.root, case)
        except ValueError as failure:
            typer.echo(f"cannot compare: {failure}", err=True)
            raise typer.Exit(1) from failure
        typer.echo(f"{result.dataset.id} against the flowsheet, case {comparison.case}, per kg")
        typer.echo(f"{'quantity':<28} {'estimate':>12} {'design':>12} {'error':>8}")
        for row in comparison.deviations:
            error = "" if row.error is None else f"{row.error:+.1%}"
            typer.echo(
                f"{row.quantity:<28} {row.estimate:>12.5g} {row.design:>12.5g} {error:>8}"
                f" {row.unit}"
            )
        for note in comparison.notes:
            typer.echo(f"note: {note}")
        return
    if as_json:
        typer.echo(result.to_json())
        return
    typer.echo(text, nl=False)


@assess_app.command("tea")
def tea(
    csv: Annotated[
        bool, typer.Option("--csv", help="The cash flow as CSV, one row per year.")
    ] = False,
    sensitivity: Annotated[
        bool, typer.Option("--sensitivity", help="Tornado and break-even values as CSV.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Premises, results, findings and provenance as JSON.")
    ] = False,
    write: Annotated[
        bool,
        typer.Option(
            "--write",
            help="Write estimate/tea.md, tea-cashflow.csv, tea-sensitivity.csv and (with a Monte "
            "Carlo) tea-uncertainty.csv.",
        ),
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when one of the TEA outputs is not current.")
    ] = False,
    compare: Annotated[
        str | None,
        typer.Option(
            "--compare",
            help="Compare with the TEA at this revision (a temporary worktree): what the two do "
            "not share, then their results.",
        ),
    ] = None,
) -> None:
    """The techno-economic analysis of the plant (Markdown by default): the capital cost built
    up from the estimate, the operating cost and revenue of the flowsheet's feeds and products,
    the discounted cash flow (NPV, IRR, LCOP, payback), scenarios, what dominates the outcome and
    what would change the decision. cheme holds no prices; every one is the project's, in
    estimate/tea.yaml with its status, source and year."""
    from chemeascode.domains.assessment.tea.report import (
        CASHFLOW_CSV,
        SENSITIVITY_CSV,
        TEA_MD,
        outputs,
        tea_report,
    )

    workspace = _workspace()
    report = tea_report(workspace.root)
    for finding in report.findings:
        typer.echo(finding.format(), err=True)
    if not report.loaded:
        raise typer.Exit(1)
    if compare is not None:
        _compare_tea(workspace, report, compare)
        return
    files = outputs(report)
    if _write_or_check(workspace, files, write, check, "tea"):
        return
    if as_json:
        typer.echo(report.to_json())
    elif csv:
        typer.echo(files[CASHFLOW_CSV], nl=False)
    elif sensitivity:
        typer.echo(files[SENSITIVITY_CSV], nl=False)
    else:
        typer.echo(files[TEA_MD], nl=False)


def _compare_tea(workspace: Workspace, report, rev: str) -> None:
    """Print the comparison of *report* with the TEA of the repository at *rev*."""
    import tempfile
    from pathlib import Path

    from chemeascode.domains.assessment.tea.report import compare, comparison_markdown, tea_report
    from chemeascode.foundation import gitinfo

    commit = gitinfo.resolve(workspace.root, rev)
    if commit is None:
        typer.echo(f"{rev} is not a revision of this repository", err=True)
        raise typer.Exit(2)
    top = gitinfo.git(workspace.root, "rev-parse", "--show-toplevel").stdout.strip()
    inner = workspace.root.resolve().relative_to(Path(top).resolve())
    with tempfile.TemporaryDirectory(prefix="cheme-tea-") as scratch:
        tree = Path(scratch) / "tree"
        added = gitinfo.git(workspace.root, "worktree", "add", "--detach", str(tree), commit)
        if added.returncode != 0:
            typer.echo(f"cannot check out {rev}: {added.stderr.strip()}", err=True)
            raise typer.Exit(2)
        try:
            other = tea_report((tree / inner).resolve())
        except NotAPlantRepository:
            typer.echo(f"no plant at {rev}: nothing to compare with", err=True)
            raise typer.Exit(1) from None
        finally:
            gitinfo.git(workspace.root, "worktree", "remove", "--force", str(tree))
    if not other.loaded:
        errors = [f for f in other.findings if f.level == "error"]
        typer.echo(
            f"the TEA at {rev} does not compute: {errors[0].message if errors else 'no result'}",
            err=True,
        )
        raise typer.Exit(1)
    found = compare(report, other, rev)
    for finding in found.findings:
        typer.echo(finding.format(), err=True)
    typer.echo(comparison_markdown(found, "working tree", rev), nl=False)


@assess_app.command("lca-search")
def lca_search(
    text: Annotated[str, typer.Argument(help="Words of the activity's name or product.")],
    database: Annotated[
        str | None, typer.Option("--database", help="Only this database of the project.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="At most this many.")] = 20,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Brightway project; default brightway.project of lca.yaml."),
    ] = None,
) -> None:
    """Find activities and flows in the Brightway project (extra lca), printed as the
    activity: or biosphere: mapping to paste into lca/lca.yaml."""
    import yaml

    from chemeascode.integrations import brightway as bw

    if project is None:
        from chemeascode.domains.assessment.lca.inventory import LCA_FILE

        workspace = _workspace()
        path = workspace.root / LCA_FILE
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
        project = ((data or {}).get("brightway") or {}).get("project")
        if not project:
            typer.echo(f"no brightway.project in {LCA_FILE}; give --project", err=True)
            raise typer.Exit(2)
    try:
        found = bw.search(project, text, database, limit)
    except bw.BrightwayUnavailable as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    except LookupError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    for item in found:
        if item["biosphere"]:
            entry = {"biosphere": {k: item[k] for k in ("database", "name", "categories")}}
        else:
            entry = {
                "activity": {
                    k: item[k]
                    for k in ("database", "name", "reference_product", "location")
                    if item[k] is not None
                }
            }
        typer.echo(f"# per {item['unit']}")
        typer.echo(
            yaml.safe_dump(entry, sort_keys=False, default_flow_style=True, width=200).strip()
        )


@assess_app.command("lca-map")
def lca_map(
    keys: Annotated[
        list[str] | None,
        typer.Argument(help="Only these exchanges (e.g. feed:POWER); default every open one."),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option("--query", help="Search with this text instead of each exchange's name."),
    ] = None,
    database: Annotated[
        str | None, typer.Option("--database", help="Only this database of the project.")
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", min=1, help="At most this many per exchange.")
    ] = 5,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Brightway project; default brightway.project of lca.yaml."),
    ] = None,
    approve: Annotated[
        list[str] | None,
        typer.Option(
            "--apply",
            help="KEY=N: write candidate N of KEY (as listed with the same --query, --database "
            "and --limit) as its activity: into lca/lca.yaml. Repeatable; needs --source.",
        ),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option("--source", help="Why these mappings (their source: in lca/lca.yaml)."),
    ] = None,
) -> None:
    """The exchanges without a background (unmapped, or declared missing:) with candidate
    activities of the Brightway project (extra lca), numbered, with the query that found them.
    A dry run: it writes nothing unless --apply names the approved candidates, and then only
    their activity: mappings."""
    import yaml

    from chemeascode.domains.assessment.lca import mapping
    from chemeascode.domains.assessment.lca.inventory import LCA_FILE
    from chemeascode.domains.assessment.lca.report import lca_report
    from chemeascode.integrations import brightway as bw

    workspace = _workspace()
    path = workspace.root / LCA_FILE
    if not path.is_file():
        typer.echo(f"no {LCA_FILE}; start one from the lca skill", err=True)
        raise typer.Exit(2)
    chosen: dict[str, int] = {}
    for item in approve or []:
        key, sep, number = item.rpartition("=")
        if not sep or not key or not number.isascii() or not number.isdigit() or int(number) < 1:
            typer.echo(f"--apply {item}: give KEY=N (N from 1, as listed)", err=True)
            raise typer.Exit(2)
        if key in chosen:
            typer.echo(f"--apply {key}: given twice; approve one candidate per exchange", err=True)
            raise typer.Exit(2)
        chosen[key] = int(number)
    if chosen and not (source and len(source.strip()) >= 3):
        typer.echo("--apply needs --source: why these mappings (e.g. DESIGN.md D-120)", err=True)
        raise typer.Exit(2)
    if query and len(set(keys or []) | set(chosen)) != 1:
        typer.echo("--query searches for one exchange: name it", err=True)
        raise typer.Exit(2)
    if project is None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        project = ((data if isinstance(data, dict) else {}).get("brightway") or {}).get("project")
        if not project:
            typer.echo(f"no brightway.project in {LCA_FILE}; give --project", err=True)
            raise typer.Exit(2)
    report = lca_report(workspace.root, inventory_only=True)
    if not report.loaded or report.inventory is None:
        for finding in report.findings:
            typer.echo(finding.format(), err=True)
        raise typer.Exit(1)
    exchanges = mapping.open_exchanges(report.inventory)
    wanted = set(keys or []) | set(chosen)
    unknown = sorted(wanted - {e.key for e in exchanges})
    if unknown:
        typer.echo(
            f"{LCA_FILE}: error cheme.lca-map-key [{', '.join(unknown)}]: no open exchange "
            f"{', '.join(unknown)} -- name a key without a background (cheme assess lca-map lists "
            "them)",
            err=True,
        )
        raise typer.Exit(1)
    if wanted:
        exchanges = [e for e in exchanges if e.key in wanted]
    try:
        mapping.search(project, exchanges, query, database, limit)
    except bw.BrightwayUnavailable as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    except LookupError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    if not chosen:
        for exchange in exchanges:
            why = (
                "no background" if exchange.reason == "unmapped" else f"missing: {exchange.detail}"
            )
            typer.echo(f"{exchange.key} ({exchange.title}, per {exchange.unit}): {why}")
            typer.echo(f"  query: {exchange.query!r} in project {project!r}")
            if exchange.unsupported:
                typer.echo(f"  --apply: not available ({exchange.unsupported})")
            if not exchange.candidates:
                typer.echo("  no candidates: try --query with other words")
            for number, candidate in enumerate(exchange.candidates, 1):
                entry = (
                    {"biosphere": {k: candidate[k] for k in ("database", "name", "categories")}}
                    if candidate["biosphere"]
                    else {"activity": mapping.activity_entry(candidate)}
                )
                flat = yaml.safe_dump(
                    entry, sort_keys=False, default_flow_style=True, width=200, allow_unicode=True
                )
                problem = mapping.compatible(exchange, candidate)
                typer.echo(
                    f"  {number}. {flat.strip()}  # per {candidate['unit']}"
                    + (f"; not applicable: {problem}" if problem else "")
                )
        typer.echo("dry run: nothing written; approve with --apply KEY=N --source TEXT", err=True)
        return
    from chemeascode.domains.assessment.lca.inventory import _line

    # bytes: the file's own line endings stay (apply keeps them)
    text = path.read_bytes().decode("utf-8")
    by_key = {e.key: e for e in exchanges}
    applied = []
    for key, number in chosen.items():
        exchange = by_key[key]
        problem = exchange.unsupported
        if not problem and number > len(exchange.candidates):
            problem = f"no candidate {number} ({len(exchange.candidates)} found)"
        if not problem:
            problem = mapping.compatible(exchange, exchange.candidates[number - 1])
        if not problem:
            activity = mapping.activity_entry(exchange.candidates[number - 1])
            try:
                text = mapping.apply(text, key, activity, source or "")
            except mapping.ApplyRefused as refused:
                problem = str(refused)
        if problem:
            ident = key.partition(":")[2]
            line = _line(text, key if key.startswith(("feed:", "product:")) else f"id: {ident}")
            typer.echo(
                f"{LCA_FILE}{f':{line}' if line else ''}: error cheme.lca-map-refused [{key}]: "
                f"{key}={number} not applied: "
                f"{problem} -- nothing was written; choose another candidate, or edit "
                f"{LCA_FILE} by hand",
                err=True,
            )
            raise typer.Exit(1)
        flat = yaml.safe_dump(
            activity, sort_keys=False, default_flow_style=True, width=200, allow_unicode=True
        )
        applied.append(f"{key}: activity: {flat.strip()}")
    path.write_bytes(text.encode("utf-8"))
    for line in applied:
        typer.echo(f"mapped {line}")
    typer.echo(f"wrote {LCA_FILE}; review the diff, then cheme assess lca --write")
