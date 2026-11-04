"""``cheme process``: build the BFD/PFD sheets, print the stream table, pin the layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

process_app = typer.Typer(
    help="Process design: BFD and PFD generated from process/materials.yaml and "
    "process/flowsheet.yaml.",
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


def _process(workspace: Workspace):
    from chemeascode.domains.process.model import load

    process, findings = load(workspace.root)
    _refuse_unloaded(process, findings)
    return process


def _refuse_unloaded(process, findings) -> None:
    """Print why the process YAML did not load and exit 1; return when it did."""
    errors = [f for f in findings if f.level == "error"]
    if process is None or errors:
        for finding in errors or findings:
            typer.echo(finding.format(), err=True)
        if process is None and not findings:
            typer.echo("process/flowsheet.yaml does not exist", err=True)
        raise typer.Exit(1)


@process_app.command("build")
def build(
    sheets: Annotated[
        list[str] | None, typer.Argument(help="Sheet ids or files (default: every bfd/pfd sheet).")
    ] = None,
    force: Annotated[
        bool, typer.Option(help="Overwrite a sheet edited by hand since it was generated.")
    ] = False,
) -> None:
    """Generate the BFD and PFD sheets (DEXPI 2.0.1 ProcessModels with a drawing).

    Refuses while the flowsheet has errors, and over a sheet edited by hand unless --force.
    """
    from chemeascode.domains.process.sheets import build as do_build

    result = do_build(_workspace(), sheets or None, force=force)
    for line in result.lines:
        typer.echo(line)
    if result.failed:
        raise typer.Exit(1)


@process_app.command("streams")
def streams(
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    md: Annotated[bool, typer.Option("--md", help="Markdown table.")] = False,
    csv: Annotated[bool, typer.Option("--csv", help="CSV.")] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Streams, balances and provenance as JSON.")
    ] = False,
) -> None:
    """The stream table (value, unit, provenance per property) and the block balances."""
    from chemeascode.domains.process.streams import (
        UnknownCase,
        stream_csv,
        stream_markdown,
        stream_report,
        stream_text,
    )

    workspace = _workspace()
    try:
        report = stream_report(workspace.root, case)
    except UnknownCase as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    _refuse_unloaded(report.process, report.findings)
    process, case = report.process, report.case
    if as_json:
        typer.echo(report.to_json())
    elif csv:
        typer.echo(stream_csv(process, case), nl=False)
    elif md:
        typer.echo(stream_markdown(process, case))
    else:
        typer.echo(stream_text(process, case))


@process_app.command("reactors")
def reactors(
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Each reactor: model, extents, heats of reaction, ln K and ln(Q/K) at the outlet, and the
    duty H(out) - H(in) on the elements basis (ideal gas)."""
    from chemeascode.domains.process.reactors import UnknownCase, reactor_report, reactor_text

    workspace = _workspace()
    try:
        report = reactor_report(workspace.root, case)
    except UnknownCase as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    _refuse_unloaded(report.process, report.findings)
    typer.echo(report.to_json() if as_json else reactor_text(report))


@process_app.command("crystallizers")
def crystallizers(
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Each crystallizer and filter or centrifuge (crystallizer:, solid_separation:): its basis
    (solubility-equilibrium, imposed-yield or solid-split), crystals, recovery, the outlets as dry
    solid and liquid, the balances and the duty. Exit 1 on an error finding."""
    from chemeascode.domains.process.crystallization import (
        UnknownCase,
        crystallizer_report,
        report_text,
    )

    workspace = _workspace()
    try:
        report = crystallizer_report(workspace.root, case)
    except UnknownCase as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    _refuse_unloaded(report.process, report.findings)
    typer.echo(report.to_json() if as_json else report_text(report))
    if not as_json:
        for finding in report.findings:
            if finding.rule.startswith("cheme.process-crystallizer"):
                typer.echo(finding.format())
    if any(f.level == "error" for f in report.findings):
        raise typer.Exit(1)


@process_app.command("reactor-uncertainty")
def reactor_uncertainty(
    node: Annotated[str, typer.Argument(help="The reactor block or step.")],
    samples: Annotated[int, typer.Option("--samples", min=10, help="Monte Carlo draws.")] = 200,
    seed: Annotated[int, typer.Option("--seed", help="Seed of the generator.")] = 1,
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The spread of NODE's conversion, outlet flows and temperatures from the uncertainty of
    its reaction data, by Monte Carlo through its own reactor model. Only what the model reads
    is sampled (rate A and Ea; K with reverse: equilibrium; heat_of_reaction for a liquid
    adiabatic tank or batch; conversion for a conversion reactor; for a selectivity: step, the
    key's conversion and the selectivities from selectivity.uncertainty, evaluated as propagate
    does); other uncertainties are listed as not used, with the reason. Writes nothing. Exit 2
    when it cannot be sampled or nothing it uses is uncertain."""
    from chemeascode.domains.process.reactor_uncertainty import (
        SamplingError,
        sample_node,
        uncertainty_text,
    )

    workspace = _workspace()
    try:
        result = sample_node(workspace.root, node, samples, seed, case)
    except SamplingError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    typer.echo(json.dumps(result.as_dict(), indent=2) if as_json else uncertainty_text(result))


@process_app.command("reactor-hazards")
def reactor_hazards(
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Thermal screening of each reactor: adiabatic temperature rise, MTSR after a cooling
    failure, MTT, TD24, Stoessel's criticality class and, for cooled beds, the hot spot's
    sensitivity to the coolant temperature (domains/safety/reaction_hazards.py). Screening
    values only. Exit 1 on a warning (class 3 to 5, an MTSR above MTT or TD24, a sensitive
    bed)."""
    from chemeascode.domains.safety.reaction_hazards import hazard_text, screen

    workspace = _workspace()
    report = screen(workspace.root, case)
    typer.echo(report.to_json() if as_json else hazard_text(report))
    if any(f.level in ("warning", "error") for f in report.findings):
        raise typer.Exit(1)


@process_app.command("reactor-choice")
def reactor_choice(
    node: Annotated[str, typer.Argument(help="The reactor block or step.")],
    product: Annotated[str, typer.Option("--product", help="The desired product.")],
    key: Annotated[
        str | None, typer.Option("--key", help="The converted component (default: first fed).")
    ] = None,
    tanks: Annotated[int, typer.Option("--tanks", min=1, help="Tanks in series to compare.")] = 3,
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    svg: Annotated[Path | None, typer.Option("--svg", help="Write the plot to this file.")] = None,
    region_svg: Annotated[
        Path | None,
        typer.Option(
            "--region-svg",
            help="Also compute the candidate attainable region and write its plot here.",
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
    as_csv: Annotated[bool, typer.Option("--csv", help="The points as CSV.")] = False,
) -> None:
    """Which ideal reactor suits NODE's reactions: the yield and selectivity of PRODUCT against
    the key's conversion for a plug-flow reactor, one stirred tank and --tanks tanks in series
    (isothermal, at the inlet's temperature and pressure), and the plug flow's instantaneous
    selectivity. --svg writes the plot. Exit 2 when it cannot be compared."""
    from chemeascode.domains.process.reactor_choice import ChoiceError, choice_svg, summary_text

    if as_json and as_csv:
        typer.echo("give --json or --csv, not both", err=True)
        raise typer.Exit(2)
    from chemeascode.domains.process.attainable_region import region
    from chemeascode.domains.process.attainable_region import region_svg as draw
    from chemeascode.domains.process.reactor_choice import _node_inputs, compare

    workspace = _workspace()
    found = None
    try:  # the plant read once; both computed before anything is written
        reactions, moles, kelvin, kpa, key, data, liquid, loading = _node_inputs(
            workspace.root, node, key, case
        )
        choice = compare(
            reactions, moles, kelvin, kpa, key, product, data, liquid, tanks, loading, node
        )
        if region_svg is not None:
            found = region(reactions, moles, kelvin, kpa, key, product, data, liquid, loading)
    except ChoiceError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if svg is not None:
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text(choice_svg(choice), encoding="utf-8")
    if region_svg is not None and found is not None:
        region_svg.parent.mkdir(parents=True, exist_ok=True)
        region_svg.write_text(draw(found), encoding="utf-8")
    if as_json:
        document = choice.as_dict()
        if found is not None:
            document["region"] = found.as_dict()
        typer.echo(json.dumps(document, indent=2))
    elif as_csv:
        typer.echo(choice.csv(), nl=False)
    else:
        typer.echo(summary_text(choice))
        if found is not None and (best := found.best()) is not None:
            typer.echo(
                f"  attainable region (candidate): highest yield {best.y:.4g} at conversion "
                f"{1 - best.x:.4g}, by {best.origin}"
            )
        for written in (svg, region_svg):
            if written is not None:
                typer.echo(f"wrote {written}")


@process_app.command("adsorption")
def adsorption(
    case: Annotated[str | None, typer.Option(help="Case id (default: every case).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Each adsorber of process/adsorption.yaml: core's equilibrium TSA cycle (breakthrough,
    recoveries, regeneration heat and purge, adsorbent replacement) from sourced isotherms, or
    an external performance model's results checked against its operating range; and whether
    the split process/simulation.yaml gives the simulator follows from it. An isotherm outside
    its stated range and a calculated PSA are refused. Writes nothing. Exit 1 on a warning or
    error, 2 for an unknown case."""
    from chemeascode.domains.process.separations.adsorption import (
        UnknownCase,
        adsorption_report,
        adsorption_text,
    )

    workspace = _workspace()
    try:
        report = adsorption_report(workspace.root, case)
    except UnknownCase as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    typer.echo(report.to_json() if as_json else adsorption_text(report))
    if any(f.level in ("warning", "error") for f in report.findings):
        raise typer.Exit(1)


@process_app.command("cell")
def cell(
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The Faraday balance of each electrochemical cell of process/cells.yaml: extents, products
    per outlet, charge and element balances, electric power, thermoneutral voltage, heat duty
    (Q = P - extent dH, electricity counted once) and kWh per kg of product, from the specified
    current, current efficiency and voltage. Refuses a cell without them. Writes nothing. Exit 1
    on an error finding (a refused or inconsistent cell), 2 without process/cells.yaml."""
    from chemeascode.domains.process.electrochemical_cell import (
        CELLS_FILE,
        cell_report,
        has_cells,
        report_text,
    )

    workspace = _workspace()
    if not has_cells(workspace.root):
        typer.echo(f"{CELLS_FILE} does not exist", err=True)
        raise typer.Exit(2)
    report = cell_report(workspace.root)
    typer.echo(report.to_json() if as_json else report_text(report))
    if any(f.level == "error" for f in report.findings):
        raise typer.Exit(1)


@process_app.command("duty")
def duty(
    ids: Annotated[list[str] | None, typer.Argument(help="Duty ids (default: every duty).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
    plot: Annotated[
        Path | None,
        typer.Option(help="Write the time plots and operating maps (SVG) into this directory."),
    ] = None,
    compare: Annotated[
        str | None,
        typer.Option(help="ID,ID: compare these duties at equal delivered product (--co)."),
    ] = None,
    co: Annotated[
        float | None, typer.Option(help="With --compare: the delivered product, kg.")
    ] = None,
    tolerance: Annotated[
        float,
        typer.Option(help="With --compare: relative tolerance on the delivered product."),
    ] = 1e-3,
) -> None:
    """The dynamic duties of process/duties.yaml: each cell's current or power schedule
    against the anolyte reservoir (voltage, efficiencies and WDE from the measured series or
    the specified cell, never extrapolated), the pH, inventory, product, charge, energy,
    dosing and bleed over time, the time to the stated pH threshold and the time outside the
    measured range. A duty a stack of process/cells.yaml names (equipment.duty) runs at the
    arrangement that stack is sized at, as in cheme process stack (cheme.duty-arrangement).
    --compare ID,ID --co KG compares duties at equal delivered product (the duties are named
    there, not as IDS; --plot then draws the compared transients). Writes nothing but the
    plots. Exit 1 on an error finding, 2 without process/duties.yaml, for an unknown duty id or
    for IDS given with --compare."""
    from chemeascode.domains.equipment.electrolyser_stack import stack_arrangements
    from chemeascode.domains.process.electrolysis_duty import (
        DUTIES_FILE,
        DutyReport,
        compare_duties,
        comparison_text,
        duty_report,
        has_duties,
        report_text,
    )

    workspace = _workspace()
    if not has_duties(workspace.root):
        typer.echo(f"{DUTIES_FILE} does not exist", err=True)
        raise typer.Exit(2)
    arrangements = stack_arrangements(workspace.root)  # one design basis with the stacks
    if compare is not None:
        if co is None:
            typer.echo("--compare needs --co KG (the delivered product)", err=True)
            raise typer.Exit(2)
        if ids:
            typer.echo(
                f"--compare names the duties to compare (ID,ID); drop {' '.join(ids)} or add "
                "them to --compare",
                err=True,
            )
            raise typer.Exit(2)
        names = [n.strip() for n in compare.split(",") if n.strip()]
        try:
            comparison = compare_duties(workspace.root, names, co, tolerance, arrangements)
        except (KeyError, ValueError) as failure:
            typer.echo(str(failure).strip("'\""), err=True)
            raise typer.Exit(2) from failure
        typer.echo(comparison.to_json() if as_json else comparison_text(comparison))
        if plot is not None:  # the compared transients, each to the target
            _duty_plots(DutyReport(comparison.duties, comparison.findings), plot, as_json)
        if any(f.level == "error" for f in comparison.findings):
            raise typer.Exit(1)
        return
    try:
        report = duty_report(workspace.root, ids or None, arrangements)
    except KeyError as failure:
        typer.echo(str(failure).strip("'\""), err=True)
        raise typer.Exit(2) from failure
    typer.echo(report.to_json() if as_json else report_text(report))
    if plot is not None:
        _duty_plots(report, plot, as_json)
    if report.errors:
        raise typer.Exit(1)


@process_app.command("stack")
def stack(
    ids: Annotated[
        list[str] | None, typer.Argument(help="Stack ids (default: every stack).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
    write: Annotated[
        bool,
        typer.Option(
            "--write",
            help="Write the calculated stack and tank dimensions into the equipment list, "
            "the pumps' inputs into their datasheets (never over a value written by hand) and "
            "a reservoir volume the duty asks for (reservoir.size: to_horizon) into "
            "process/duties.yaml.",
        ),
    ] = False,
) -> None:
    """The stacks of the stacks: section of process/cells.yaml sized for their product duty
    at the cell's operating point (never outside its measured or declared range): active area,
    cells, cells per stack from the voltage limit, stacks, stack voltage and current, DC power,
    output and its margin, kWh per kg, the stack envelope; and the skid equipment inputs from
    the duty named, run at the sized arrangement over its horizon: reservoir and tank
    dimensions (a dosing or bleed tank over its refill or emptying interval), the recirculation
    and dosing pumps' flows, and with the duty's reservoir.size: to_horizon the reservoir volume
    that reaches its horizon. Without --write it writes nothing and reports what differs from
    the equipment list, the datasheets and process/duties.yaml (cheme.stack-outdated); --write
    writes them (a reservoir volume first, then the tanks from the duty at it); with --write
    --json the report (as the files are then) carries `written`, each file written with its
    tags (or duty ids).
    Exit 1 on an error finding (process/cells.yaml not following its schema among them: its
    findings are printed), 2 without process/cells.yaml or stacks, or for an unknown id."""
    from chemeascode.domains.equipment.electrolyser_stack import (
        has_stacks,
        report_text,
        stack_report,
        write_stack_inputs,
    )
    from chemeascode.domains.process.electrochemical_cell import CELLS_FILE, has_cells
    from chemeascode.domains.process.electrolysis_duty import DUTIES_FILE

    workspace = _workspace()
    if not has_cells(workspace.root):
        typer.echo(f"{CELLS_FILE} does not exist", err=True)
        raise typer.Exit(2)
    if not has_stacks(workspace.root):
        loaded = stack_report(workspace.root)  # a file that does not load: its findings
        if loaded.errors:
            typer.echo(loaded.to_json() if as_json else report_text(loaded))
            raise typer.Exit(1)
        typer.echo(f"{CELLS_FILE} has no stacks: section", err=True)
        raise typer.Exit(2)
    try:
        report = stack_report(workspace.root, ids or None)
    except KeyError as failure:
        typer.echo(str(failure).strip("'\""), err=True)
        raise typer.Exit(2) from failure
    if write:
        try:
            written = write_stack_inputs(workspace.root, report)
            if DUTIES_FILE in written.written:
                # a reservoir volume written (reservoir.size: to_horizon): the tanks follow
                # from the duty at that volume, in a second pass
                again = write_stack_inputs(
                    workspace.root, stack_report(workspace.root, ids or None)
                )
                for name, tags in again.written.items():
                    written.written[name] = sorted({*written.written.get(name, []), *tags})
        except ValueError as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(1) from failure
        report = stack_report(workspace.root, ids or None)  # as the files are now
        if as_json:
            # the report as the files are now, and what this run wrote (file -> tags)
            payload = {**report.as_dict(), "written": written.written}
            typer.echo(json.dumps(payload, indent=2))
            if report.errors:
                raise typer.Exit(1)
            return
        for name, tags in written.written.items():
            typer.echo(f"wrote {name}: {', '.join(tags)}")
        if not written.written:
            typer.echo("nothing to write")
    typer.echo(report.to_json() if as_json else report_text(report))
    if report.errors:
        raise typer.Exit(1)


def _duty_plots(report, directory: Path, as_json: bool) -> None:
    from chemeascode.domains.process.electrolysis_plots import duty_plots

    directory.mkdir(parents=True, exist_ok=True)
    for name, svg in duty_plots(report).items():
        (directory / name).write_text(svg, encoding="utf-8")
        if not as_json:
            typer.echo(f"wrote {directory / name}")


@process_app.command("energy")
def energy(
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Energy balances of blocks and steps (stream enthalpies against energy streams), the
    energy audit of the recorded simulation run, and the boundary-completeness gaps (utilities,
    waste and emission terminals not declared). Exit 1 on a warning or error."""
    from chemeascode.domains.assessment.flows import boundary_gaps
    from chemeascode.domains.process.energy import energy_report, energy_text

    workspace = _workspace()
    process = _process(workspace)
    if case is not None and case not in {c.id for c in process.flowsheet.cases}:
        typer.echo(f"unknown case {case!r}", err=True)
        raise typer.Exit(2)
    report = energy_report(workspace.root, process, case)
    gaps = boundary_gaps(process)
    findings = [*report.findings, *gaps.findings]
    if as_json:
        from chemeascode.foundation.schemas.run import finding_dict

        payload = {
            **report.entry(),
            "boundary": gaps.entry(),
            "findings": [finding_dict(f) for f in findings],
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(energy_text(report))
        for finding in findings:
            typer.echo(finding.format())
    if any(f.level in ("warning", "error") for f in findings):
        raise typer.Exit(1)


@process_app.command("pinch")
def pinch(
    dt_min: Annotated[
        float,
        typer.Option(
            "--dt-min", help="The global minimum approach temperature dTmin, K (required)."
        ),
    ],
    dt_min_source: Annotated[
        str,
        typer.Option(
            "--dt-min-source", help="Where dTmin comes from (recorded; default: ASSUMED)."
        ),
    ] = "ASSUMED",
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    include_constrained: Annotated[
        bool,
        typer.Option(
            "--include-constrained",
            help="Include the constrained duties (reactors) in the targets, as a sensitivity.",
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
    md: Annotated[bool, typer.Option("--md", help="As Markdown.")] = False,
    write: Annotated[
        bool, typer.Option("--write", help="Record the targets in process/pinch-run.json.")
    ] = False,
) -> None:
    """Whole-plant pinch targets of the case's recorded simulation run
    (process/simulation-run.json, from cheme process simulate --fill; the simulator is not run).

    Prints the current utility demand, the theoretical minimum utility demand at dTmin and the
    theoretical energy-saving potential (their difference: not a saving), the hot-side,
    cold-side and shifted pinch (or a threshold problem), the utility-use pinch violations
    apart from cross-pinch transfer in existing exchangers, the thermal streams with class and
    quality, and the reconciliation against the run's duties. --write records the result in
    process/pinch-run.json. Exit 1 on an error (no current converged run, too few streams) or a
    reconciliation finding; 2 on invalid input; 3 when --write is refused (a reconciliation
    finding), nothing written."""
    from chemeascode.domains.process.heat_integration.report import (
        PINCH_FILE,
        UnknownCase,
        pinch_markdown,
        pinch_report,
        pinch_text,
    )
    from chemeascode.domains.process.heat_integration.report import write as record

    if as_json and md:
        typer.echo("give --json or --md, not both", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    process = _process(workspace)
    try:
        report = pinch_report(
            workspace.root,
            process,
            case,
            dt_min,
            dt_min_source=dt_min_source,
            include_constrained=include_constrained,
        )
    except (UnknownCase, ValueError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if as_json:
        typer.echo(report.to_json())
    elif md:
        typer.echo(pinch_markdown(report))
    else:
        typer.echo(pinch_text(report))
    if report.failed:
        raise typer.Exit(1)
    if write:
        if report.unreconciled:
            typer.echo(
                f"refused: {PINCH_FILE} not written, the reconciliation has a finding (heat of "
                "the run the extracted streams do not give back)",
                err=True,
            )
            raise typer.Exit(3)
        record(workspace.root, report)
        typer.echo(f"{PINCH_FILE}: targets of case {report.case} recorded", err=as_json)
    if any(f.level in ("warning", "error") for f in report.findings):
        raise typer.Exit(1)


@process_app.command("furnace")
def furnace(
    furnace_id: Annotated[
        str | None, typer.Argument(help="Furnace id (default: every furnace).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Energy basis of the solid-reaction furnaces of process/furnaces.yaml (lime calcination):
    element balance, product and off-gas composition, reaction enthalpy and the furnace energy
    closure from condensed-phase NASA data (extra `cantera`), or a labelled specific-energy
    fallback. Exit 1 on a warning or error."""
    from chemeascode.domains.process.furnace import furnace_report, furnace_text

    workspace = _workspace()
    try:
        report = furnace_report(workspace.root, furnace_id)
    except KeyError as failure:
        typer.echo(f"unknown furnace {furnace_id!r}", err=True)
        raise typer.Exit(2) from failure
    if as_json:
        typer.echo(json.dumps(report.entry(), indent=2))
    else:
        text = furnace_text(report)
        if text:
            typer.echo(text)
        for finding in report.findings:
            typer.echo(finding.format())
    if any(f.level in ("warning", "error") for f in report.findings):
        raise typer.Exit(1)


@process_app.command("props")
def props(
    fill: Annotated[
        bool, typer.Option("--fill", help="Write calculated values and the method.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Recalculate and report; write nothing.")
    ] = False,
    coverage: Annotated[
        bool,
        typer.Option(
            "--coverage",
            help="List the property package and, per stream, whether it covers it or why not; "
            "write nothing.",
        ),
    ] = False,
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="The run as an adapter result (JSON).")
    ] = False,
) -> None:
    """Stream properties (phase, vapour fraction, molar mass, density, enthalpy) through thermo
    (extra `props`), with the process's property package, inside its validated range only.

    --fill never overwrites given or assumed values; a state outside the range is refused and
    not written, and values calculated earlier stay and are reported stale. --fill exits 3 when
    it refused a stream (out of range, unsupported, failed or a contradicted phase) and wrote the
    rest. --check exits 1 on a warning (stale, differing or out-of-range values). --coverage
    names the package (materials.yaml property_method.package, or the one covering the most
    streams) and per stream whether it covers its components and state or why not, nearest other
    package included; it needs no thermo and exits 0 unless the recorded package is unknown.
    --json prints the run as an adapter result (cheme/adapter-result/v1) per case, same exit
    codes (with --coverage: the coverage as JSON)."""
    from chemeascode.domains.process.fill import run

    if fill + check + coverage != 1:
        typer.echo("give one of --fill, --check or --coverage", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    process = _process(workspace)
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        typer.echo(f"unknown case {case!r}", err=True)
        raise typer.Exit(2)
    if coverage:
        from chemeascode.domains.process.fill import coverage as list_coverage

        listed = list_coverage(process, case)
        if as_json:
            typer.echo(json.dumps({"lines": listed.lines, "coverage": listed.coverage}, indent=2))
        else:
            _report(listed, False)
        if any(f.level == "error" for f in listed.findings):
            raise typer.Exit(1)
        return
    result = run(workspace, process, case, write=fill)
    _report(result, as_json)
    levels = {f.level for f in result.findings}
    if "error" in levels or (check and "warning" in levels):
        raise typer.Exit(1)
    if result.refused:
        raise typer.Exit(3)


def _report(result, as_json: bool) -> None:
    """The lines and findings of a props or propagate run, or with *as_json* its adapter
    result: ``{"lines": [...], "results": [<cheme/adapter-result/v1>]}``."""
    if as_json:
        results = [result.adapter.as_dict()] if result.adapter is not None else []
        typer.echo(json.dumps({"lines": result.lines, "results": results}, indent=2))
        return
    for line in result.lines:
        typer.echo(line)
    for finding in result.findings:
        typer.echo(finding.format())


@process_app.command("propagate")
def propagate(
    fill: Annotated[
        bool, typer.Option("--fill", help="Write the derived compositions and flows.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Derive and report; write nothing.")
    ] = False,
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="The run as an adapter result (JSON).")
    ] = False,
) -> None:
    """Derive missing compositions and flows through steps their streams fully determine:
    pass-through steps (compressors, coolers, heaters, pumps, filters), mixers, splitters
    (`split:` fractions per outlet port, else the mass balance remainder).

    Separators and reactors are only checked, never solved. Derived values are `calculated`
    with an input fingerprint; given and assumed values are never overwritten. --check exits 1
    on a warning (stale propagated values). --json prints the run as an adapter result
    (cheme/adapter-result/v1) per case, same exit codes."""
    from chemeascode.domains.process.propagate import failed_result, run

    if fill == check:
        typer.echo("give --fill or --check", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    process = _process(workspace)
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        typer.echo(f"unknown case {case!r}", err=True)
        raise typer.Exit(2)
    try:
        result = run(workspace, process, case, write=fill)
    except ValueError as failure:
        if as_json:
            failed = failed_result(workspace.root, case, str(failure)).as_dict()
            typer.echo(json.dumps({"lines": [], "results": [failed]}, indent=2))
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    _report(result, as_json)
    levels = {f.level for f in result.findings}
    if "error" in levels or (check and "warning" in levels):
        raise typer.Exit(1)


@process_app.command("simulate")
def simulate(
    fill: Annotated[
        bool, typer.Option("--fill", help="Write the simulated values streams lack.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Simulate and report; write nothing.")
    ] = False,
    case: Annotated[str | None, typer.Option(help="Case id (default: the default case).")] = None,
    save: Annotated[
        Path | None,
        typer.Option(help="Also save the DWSIM flowsheet here (.dwxmz; DWSIM only)."),
    ] = None,
) -> None:
    """Solve the flowsheet in DWSIM, or in IDAES where process/simulation.yaml says simulator:
    idaes (optional; CHEME_IDAES_PYTHON names a Python with idaes-pse): feeds from
    process/flowsheet.yaml, simulator, property package and step specifications from
    process/simulation.yaml.

    --fill writes temperature, pressure, flow and composition of every simulated stream that
    lacks them (and the duty of energy streams) as `calculated` with a fingerprint; given and
    assumed values are never overwritten, a deviation from them is a warning. --fill also
    records the run (convergence, unit results, stream values, input fingerprints) in
    process/simulation-run.json; --check reports a record made from other inputs. Exits 1 on an
    error (unmapped step, missing spec or feed, no simulator) and, with --check, on a warning
    (stale or deviating values, a stale record); 3 when the simulation did not converge (no
    stream value written, the run recorded)."""
    from chemeascode.domains.process.simulation.run import run

    if fill == check:
        typer.echo("give --fill or --check", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    process = _process(workspace)
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        typer.echo(f"unknown case {case!r}", err=True)
        raise typer.Exit(2)
    try:
        result = run(workspace, process, case, write=fill, save=save)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    for line in result.lines:
        typer.echo(line)
    for finding in result.findings:
        typer.echo(finding.format())
    levels = {f.level for f in result.findings}
    if "error" in levels or (check and "warning" in levels):
        raise typer.Exit(1)
    if result.refused:
        raise typer.Exit(3)


@process_app.command("phase")
def phase(
    components: Annotated[list[str], typer.Argument(help="Component names or CAS numbers.")],
    model: Annotated[
        str | None,
        typer.Option(help="Equation of state: Peng-Robinson, Redlich-Kwong-Soave, Redlich-Kwong."),
    ] = None,
    liquid: Annotated[
        str | None, typer.Option(help="Activity-coefficient model: NRTL, Wilson, UNIFAC.")
    ] = None,
    vapor: Annotated[
        str | None, typer.Option(help="With --liquid: an equation of state or ideal_gas.")
    ] = None,
    z: Annotated[
        str | None, typer.Option(help="Overall mole fractions, comma-separated (mixtures).")
    ] = None,
    temperature: Annotated[float | None, typer.Option(help="Flash temperature.")] = None,
    temperature_unit: Annotated[str, typer.Option(help="Unit of the temperature.")] = "K",
    pressure: Annotated[float | None, typer.Option(help="Flash pressure (absolute).")] = None,
    pressure_unit: Annotated[str, typer.Option(help="Unit of the pressure.")] = "bar(a)",
    two_liquids: Annotated[
        bool, typer.Option("--two-liquids", help="Allow a second liquid (stated assumption).")
    ] = False,
    accept_zero: Annotated[
        list[str] | None,
        typer.Option(help="A pair A:B whose missing parameter is accepted as zero (repeatable)."),
    ] = None,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when a binary parameter is missing.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="The result as JSON.")] = False,
) -> None:
    """Binary interaction parameter coverage and, with --temperature and --pressure, a flash
    (phase identification) through thermo (extra `props`). No solids, electrolytes or
    pseudocomponents; no application range claimed.

    Each pair is `sourced` (with its source), `missing` (the calculation uses zero) or
    `accepted_zero` (--accept-zero). Exits 2 on invalid input, 1 with --check when a pair is
    missing."""
    from chemeascode.domains.process.thermodynamics.coverage import (
        interaction_parameter_coverage,
    )
    from chemeascode.domains.process.thermodynamics.phase import phase_determination

    if (model is None) == (liquid is None) or (liquid is not None and vapor is None):
        typer.echo("give --model, or --liquid with --vapor", err=True)
        raise typer.Exit(2)
    spec = {"eos_model": model} if model else {"liquid_phase_model": liquid}
    if liquid:
        spec["vapor_phase_model"] = vapor
    accepted = []
    for pair in accept_zero or []:
        parts = pair.split(":")
        if len(parts) != 2 or not all(parts):
            typer.echo(f"--accept-zero {pair!r}: give A:B", err=True)
            raise typer.Exit(2)
        accepted.append((parts[0], parts[1]))
    try:
        fractions = [float(x) for x in z.split(",")] if z else None
        if temperature is not None and pressure is not None:
            result = phase_determination(
                components=components,
                overall_composition=fractions,
                temperature_value=temperature,
                temperature_unit=temperature_unit,
                pressure_value=pressure,
                pressure_unit=pressure_unit,
                thermodynamic_model=spec,
                allow_two_liquids=two_liquids,
                accepted_zeros=accepted,
            )
            coverage = result.interaction_parameters
        elif temperature is not None or pressure is not None:
            typer.echo("give both --temperature and --pressure for a flash", err=True)
            raise typer.Exit(2)
        else:
            result = None
            coverage = interaction_parameter_coverage(components, spec, accepted)
    except (ValueError, ImportError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if as_json:
        payload = result.model_dump(mode="json") if result else coverage.model_dump(mode="json")
        typer.echo(json.dumps(payload, indent=2))
    else:
        if result is not None:
            typer.echo(
                f"{result.temperature_K:.2f} K, {result.pressure_Pa:.0f} Pa: "
                f"{result.gas_count} gas, {result.liquid_count} liquid; betas "
                + ", ".join(f"{b:.6g}" for b in result.betas)
                + f" (method {result.method or '?'}; {result.source})"
            )
            for note in result.notes:
                typer.echo(f"note: {note}")
            typer.echo(f"application range: {result.application_range}")
            for limitation in result.limitations:
                typer.echo(f"limitation: {limitation}")
        else:
            for note in coverage.notes:
                typer.echo(f"note: {note}")
        for line in coverage.lines():
            typer.echo(line)
    if check and coverage.missing:
        raise typer.Exit(1)


@process_app.command("extract")
def extract(
    unit: Annotated[
        str | None, typer.Argument(help="One unit of process/extraction.yaml (default: all).")
    ] = None,
    systems: Annotated[
        bool, typer.Option("--systems", help="List the bundled LLE systems and exit.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="{lines, results: [adapter result per unit]}.")
    ] = False,
) -> None:
    """Liquid-liquid extraction from process/extraction.yaml: countercurrent equilibrium stages
    on NRTL (thermo, extra `props`) with a bundled or a sourced LLE system. Prints raffinate,
    extract, solute recovery, solvent loss, distribution and selectivity, closure, and whether
    the result is inside a benchmarked range (qualified). Solvent regeneration is a separate
    unit. Writes nothing. Exit 1 when a unit is refused (e.g. no two-phase region), fails or
    does not converge, 2 without the file or for an unknown unit."""
    from chemeascode.domains.process.separations.extraction import (
        extraction_report,
        extraction_text,
        systems_table,
    )

    if systems:
        table = systems_table()
        if as_json:
            typer.echo(json.dumps(table, indent=2))
            return
        for row in table:
            claim = (
                f"benchmarked by {row['benchmark']} against {row['reference']}"
                if row["qualified"]
                else "not benchmarked"
            )
            low, high = row["temperature_K"]
            typer.echo(
                f"{row['id']}: {', '.join(row['components'])}; {low:g}-{high:g} K; "
                f"parameters: {row['source']}; {claim}"
            )
        return
    workspace = _workspace()
    try:
        report = extraction_report(workspace.root, unit)
    except (FileNotFoundError, KeyError) as failure:
        typer.echo(str(failure).strip("'\""), err=True)
        raise typer.Exit(2) from failure
    text = extraction_text(report)
    if as_json:
        payload = {
            "lines": text.splitlines(),
            "results": [r.as_dict() for r in report.adapter_results()],
            "findings": report.as_dict()["findings"],
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(text)
    if not report.ok:
        raise typer.Exit(1)


@process_app.command("methods")
def methods(
    as_json: Annotated[bool, typer.Option("--json", help="The table as JSON.")] = False,
) -> None:
    """The supported-method contract (methods.yml): per thermodynamic model the selection tree
    can recommend, whether `cheme process phase` and `cheme process simulate` run it, else its
    explicit substitute; and the coverage decisions for electrolytes, solids and
    pseudocomponents."""
    from chemeascode.domains.process.thermodynamics.methods import (
        ROUTES,
        method_table,
        route_support,
    )

    table = method_table()
    if as_json:
        typer.echo(json.dumps(table.model_dump(mode="json"), indent=2))
        return
    for m in table.methods:
        cells = []
        for route in ROUTES:
            support = route_support(m.id, route)
            if support.executable:
                cells.append(f"{route}: yes ({support.package or support.model})")
            elif support.substitution:
                cells.append(f"{route}: no, substitute {support.substitution.method}")
            else:
                cells.append(f"{route}: no, unsupported")
        typer.echo(f"{m.id}: {m.name}; " + "; ".join(cells))
        claim = m.simulation.application_range if m.simulation else None
        if claim is not None:
            typer.echo(
                f"  simulation range claimed: {', '.join(claim.components.values())}"
                f"{'' if claim.mixtures else ', each alone (no mixture)'} "
                f"({', '.join(claim.phases)}), {claim.simulator} {claim.simulator_version}, "
                f"benchmarked by {claim.benchmark.test} (--json for the boxes and tolerances)"
            )
        if m.electrolyte is not None:
            typer.echo(
                f"  electrolyte route: {', '.join(m.electrolyte.systems)} only "
                "(cheme process electrolyte, electrolytes.yml)"
            )
    for name, decision in table.regimes.items():
        others = "".join(f", {k} {v.status}" for k, v in decision.elsewhere.items())
        typer.echo(
            f"regime {name}: phase {decision.phase.status}, "
            f"simulation {decision.simulation.status}{others}"
        )


@process_app.command("electrolyte")
def electrolyte(
    temperature: Annotated[float, typer.Option(help="Temperature.")],
    pressure: Annotated[float, typer.Option(help="Pressure (absolute).")],
    molality: Annotated[
        float | None, typer.Option(help="Molality of the salt, mol per kg of water.")
    ] = None,
    mass_fraction: Annotated[
        float | None, typer.Option(help="Mass fraction of the salt in the solution.")
    ] = None,
    species: Annotated[
        str | None, typer.Option(help="Solute species molalities, e.g. 'Na+=1,Cl-=1'.")
    ] = None,
    system: Annotated[str, typer.Option(help="The electrolyte system.")] = "NaCl-H2O",
    temperature_unit: Annotated[str, typer.Option(help="Unit of the temperature.")] = "K",
    pressure_unit: Annotated[str, typer.Option(help="Unit of the pressure.")] = "bar(a)",
    as_json: Annotated[bool, typer.Option("--json", help="The result as JSON.")] = False,
) -> None:
    """Mean ionic activity coefficient, osmotic coefficient, water activity and vapour
    pressure, and relative enthalpy of a qualified aqueous electrolyte system (electrolytes.yml;
    today NaCl-H2O) through Pitzer's equations in Cantera (extras `cantera` and `props`).

    Inside the claimed range only: anything else (another salt or ion, a charge imbalance, a
    state outside the range, a boiling solution) is refused with exit code 3. Exit 2 on invalid
    input or a missing extra."""
    from chemeascode.domains.process.thermodynamics.electrolytes import (
        ElectrolyteError,
        electrolyte_state,
    )
    from chemeascode.foundation.units import convert_units

    try:
        solutes = None
        if species is not None:
            solutes = {}
            for item in species.split(","):
                name, _, value = item.partition("=")
                solutes[name.strip()] = float(value)
        result = electrolyte_state(
            convert_units(temperature, temperature_unit, "K"),
            convert_units(pressure, pressure_unit, "kPa"),
            system=system,
            molality=molality,
            mass_fraction=mass_fraction,
            species=solutes,
        )
    except ElectrolyteError as refusal:
        typer.echo(f"refused {refusal.rule}: {refusal.message} -- {refusal.hint}", err=True)
        raise typer.Exit(3) from refusal
    except (ValueError, ImportError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if as_json:
        typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return
    phi_l = result.relative_apparent_molar_enthalpy_J_per_mol
    typer.echo(
        f"{result.system} at {result.temperature_K:.2f} K, {result.pressure_kPa:.6g} kPa(a), "
        f"{result.molality_mol_per_kg:.6g} mol/kg (mass fraction {result.mass_fraction:.6g}): "
        f"one liquid phase"
    )
    typer.echo(
        f"mean activity coefficient (molality scale): {result.mean_activity_coefficient:.5f}"
    )
    typer.echo(f"osmotic coefficient: {result.osmotic_coefficient:.5f}")
    typer.echo(
        f"water activity: {result.water_activity:.6f}; water vapour pressure "
        f"{result.water_vapour_pressure_kPa:.6g} kPa(a) (pure water "
        f"{result.pure_water_vapour_pressure_kPa:.6g})"
    )
    typer.echo(
        "relative apparent molar enthalpy: "
        + (f"{phi_l:.1f} J/mol" if phi_l is not None else "not claimed at this temperature")
    )
    typer.echo(
        f"closure: charge {result.closure.charge_mol_per_kg:.3g} mol/kg, elements within "
        f"{result.closure.max_relative_deviation:.3g}"
    )
    typer.echo(f"method {result.method}: {result.solver}; parameters: {result.parameter_source}")
    typer.echo(f"benchmark: {result.benchmark.test}; tolerances {result.tolerances}")
    for note in result.notes:
        typer.echo(f"note: {note}")
    for limitation in result.limitations:
        typer.echo(f"limitation: {limitation}")


@process_app.command("assay")
def assay(
    ids: Annotated[list[str] | None, typer.Argument(help="Assay ids (default: all).")] = None,
    fill: Annotated[bool, typer.Option("--fill", help="Record the characterisations.")] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Report a missing or stale record; write nothing.")
    ] = False,
    prune: Annotated[
        bool, typer.Option("--prune", help="With --fill: drop entries of removed assays.")
    ] = False,
    temperature: Annotated[
        float | None, typer.Option(help="Flash temperature, K (with --pressure).")
    ] = None,
    pressure: Annotated[
        float | None,
        typer.Option(help="Flash pressure, kPa(a): bubble and dew points, or a flash at it."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="The result as JSON.")] = False,
) -> None:
    """Characterise the petroleum assays of process/assays.yaml into pseudocomponents
    (Riazi-Daubert, Lee-Kesler, Lastovka-Shaw; D86 converted to TBP by API 3A1.1) and print
    them with their identities and the characterisation fingerprint. An insufficient assay or
    one outside the correlations' range is refused (no pseudocomponents).

    --pressure adds the bubble and dew temperatures, --temperature with --pressure a
    Peng-Robinson flash (kij = 0), each with why it lies outside the benchmarked claim. --fill
    records the characterisations in process/assay-characterization.json; --check reports a
    record made from other inputs or another method version. Exits 1 on an error (with --check
    also on a warning), 2 on a wrong call."""
    from chemeascode.domains.process.thermodynamics import assay as assays
    from chemeascode.foundation.schemas.run import finding_dict

    if (fill and check) or (prune and not fill):
        typer.echo("--fill and --check exclude each other; --prune needs --fill", err=True)
        raise typer.Exit(2)
    if temperature is not None and pressure is None:
        typer.echo("--temperature needs --pressure", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    if not (workspace.root / assays.ASSAYS_FILE).is_file():
        typer.echo(f"no {assays.ASSAYS_FILE}", err=True)
        raise typer.Exit(2)
    try:
        report = assays.assay_report(workspace.root, ids or None)
    except KeyError as failure:
        typer.echo(f"unknown assay {failure.args[0]!r}", err=True)
        raise typer.Exit(2) from failure
    except ImportError as failure:
        typer.echo(f"{failure}: pip install 'cheme-as-code[props]'", err=True)
        raise typer.Exit(2) from failure
    findings = report.all_findings()
    states: dict[str, dict] = {}
    for c in report.characterizations:
        if pressure is None or c.refused:
            continue
        state = assays.saturation(c, pressure)
        if temperature is not None:
            state["flash"] = assays.flash(c, temperature, pressure).as_dict()
        states[c.assay] = state
    written: list[str] = []
    removed: list[str] = []
    if fill:
        written = assays.fill(workspace.root, report)
        removed = assays.prune(workspace.root) if prune else []
    if check or fill:
        findings += assays.record_findings(workspace.root, missing=check)
    if as_json:
        data = {
            "characterizations": [c.as_dict() for c in report.characterizations],
            "states": states,
            "findings": [finding_dict(f) for f in findings],
            "recorded": written,
            "removed": removed,
            "source": report.source.as_dict() if report.source else None,
        }
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        for c in report.characterizations:
            if c.refused:
                typer.echo(f"assay {c.assay}: refused (method {c.method_version})")
                continue
            bulk = c.bulk
            typer.echo(
                f"assay {c.assay}: {len(c.pseudocomponents)} pseudocomponents, fingerprint "
                f"{c.fingerprint} (method {c.method_version}); SG {bulk['specific_gravity']:.4f}"
                f", M {bulk['molar_mass']:.1f} g/mol"
            )
            for p in c.pseudocomponents:
                typer.echo(
                    f"  {p.identity}  {p.name}: x_vol {p.volume_fraction:.4f} x_mass "
                    f"{p.mass_fraction:.4f} x_mol {p.mole_fraction:.4f}  Tb "
                    f"{p.normal_boiling_point_K:.1f} K  SG {p.specific_gravity:.4f}  M "
                    f"{p.molar_mass:.1f}  Tc {p.critical_temperature_K:.1f} K  Pc "
                    f"{p.critical_pressure_Pa / 1e3:.0f} kPa  omega {p.acentric_factor:.4f}"
                )
            state = states.get(c.assay)
            if state:
                typer.echo(
                    f"  at {pressure:g} kPa(a): bubble {state['bubble_temperature_K']:.2f} K, "
                    f"dew {state['dew_temperature_K']:.2f} K"
                )
                if "flash" in state:
                    f = state["flash"]
                    typer.echo(
                        f"  flash {temperature:g} K: {f['phase']}, vapour fraction "
                        f"{f['vapour_fraction']:.4f}, H {f['enthalpy_J_per_kg'] / 1e3:.2f} kJ/kg "
                        "(ideal gas at 298.15 K = 0)"
                    )
                for reason in state["outside_claim"] + (state.get("flash") or {}).get(
                    "outside_claim", []
                ):
                    typer.echo(f"  outside the benchmarked claim: {reason}")
        for line in written:
            typer.echo(f"recorded {line} in {assays.RECORD_FILE}")
        for line in removed:
            typer.echo(f"removed {line} from {assays.RECORD_FILE}")
        for finding in findings:
            typer.echo(finding.format())
    levels = {f.level for f in findings}
    if "error" in levels or (check and "warning" in levels):
        raise typer.Exit(1)


@process_app.command("layout")
def layout(
    ids: Annotated[
        list[str] | None, typer.Argument(help="Object ids to pin (default: every node).")
    ] = None,
    view: Annotated[str, typer.Option(help="bfd or pfd.")] = "bfd",
    pin: Annotated[
        bool, typer.Option("--pin", help="Write the positions as overrides into the flowsheet.")
    ] = False,
) -> None:
    """Print the generated layout of a view; --pin writes it into flowsheet.yaml layout.<view>
    so later builds keep those positions."""
    from chemeascode.domains.process.streams import layout_rows, pin_layout

    if view not in ("bfd", "pfd"):
        typer.echo("--view is bfd or pfd", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    process = _process(workspace)
    rows = layout_rows(process, view, ids or None)
    for row in rows:
        typer.echo(row)
    if pin:
        typer.echo(pin_layout(workspace, process, view, ids or None))
