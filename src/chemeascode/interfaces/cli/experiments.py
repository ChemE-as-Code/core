"""``cheme experiments``: kinetic data and the rate laws fitted to them
(domains/experiments/kinetic_fit.py, project/kinetics.py), and measured electrochemical series
(domains/experiments/electrochemistry.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

experiments_app = typer.Typer(
    help="Experiments: kinetic data, rate laws fitted to them, data sampled from a mechanism, "
    "measured electrochemical series.",
    no_args_is_help=True,
)


def _pairs(entries: list[str] | None, what: str) -> dict[str, str]:
    out = {}
    for entry in entries or []:
        key, eq, value = entry.partition("=")
        if not eq or not key or not value:
            typer.echo(f"{entry!r}: give {what}", err=True)
            raise typer.Exit(2)
        out[key] = value
    return out


@experiments_app.command("fit-rate")
def fit_rate(
    data: Annotated[Path, typer.Argument(help="A kinetic data file (cheme/kinetic-data/v1).")],
    form: Annotated[str, typer.Option(help="power_law or lhhw.")] = "power_law",
    order: Annotated[
        list[str] | None,
        typer.Option(
            help="Power law: a component with an order (repeat; default: the reactants). LHHW: "
            "ID=EXPONENT of the numerator."
        ),
    ] = None,
    adsorb: Annotated[
        list[str] | None, typer.Option(help="LHHW: a component in the denominator (repeat).")
    ] = None,
    power: Annotated[float, typer.Option(help="LHHW: the denominator's exponent.")] = 1.0,
    reverse: Annotated[
        bool, typer.Option("--reverse", help="Fit r / (1 - Q/K): the reaction is reversible.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Fit a rate law to kinetic data: the law as a `rate:` entry for process/reactions.yaml,
    each parameter with its standard error and 95 % interval, and the R^2 of ln r."""
    from chemeascode.interfaces.cli.process import _workspace
    from chemeascode.project.kinetics import fit_dict, fit_file, fit_text

    root = _workspace().root
    orders: dict[str, float] = {}
    names: list[str] = []
    for entry in order or []:
        if "=" in entry:
            key, _, value = entry.partition("=")
            try:
                orders[key] = float(value)
            except ValueError as failure:
                typer.echo(f"{entry!r}: give ID=EXPONENT", err=True)
                raise typer.Exit(2) from failure
        else:
            names.append(entry)
    if form == "power_law" and orders:
        typer.echo("a power law fits its orders: give --order ID (no =EXPONENT)", err=True)
        raise typer.Exit(2)
    if form == "lhhw" and names:
        typer.echo("an LHHW numerator takes fixed orders: give --order ID=EXPONENT", err=True)
        raise typer.Exit(2)
    try:
        fit = fit_file(root, data, form, names, orders, adsorb or [], power, reverse)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    typer.echo(json.dumps(fit_dict(fit), indent=2) if as_json else fit_text(fit))


@experiments_app.command("sample-mechanism")
def sample(
    reaction: Annotated[str, typer.Argument(help="A reaction with a mechanism.")],
    temperature: Annotated[list[float], typer.Option("--temperature", "-T", help="K (repeat).")],
    pressure: Annotated[
        list[str],
        typer.Option("--pressure", "-p", help="ID=BAR,BAR,... partial pressures (repeat)."),
    ],
    sites_per_kg: Annotated[float, typer.Option(help="kmol of active sites per kg of catalyst.")],
    out: Annotated[Path, typer.Option(help="The kinetic data file to write.")],
    product: Annotated[str | None, typer.Option(help="Default: the first product.")] = None,
) -> None:
    """Sample a reaction's mechanism over a grid of conditions into a kinetic data file, to fit a
    rate law for a fixed bed with `cheme experiments fit-rate`."""
    from chemeascode.interfaces.cli.process import _workspace
    from chemeascode.project.kinetics import data_yaml, sample_file

    grid = {}
    for key, values in _pairs(pressure, "ID=BAR,BAR,...").items():
        try:
            grid[key] = [float(v) for v in values.split(",")]
        except ValueError as failure:
            typer.echo(f"{key}={values}: give numbers in bar", err=True)
            raise typer.Exit(2) from failure
    if sites_per_kg <= 0 or any(t <= 0 for t in temperature):
        typer.echo("--sites-per-kg and the temperatures are above 0", err=True)
        raise typer.Exit(2)
    root = _workspace().root
    try:
        data = sample_file(root, reaction, temperature, grid, sites_per_kg, product)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(data_yaml(data), encoding="utf-8")
    typer.echo(f"{out}: {len(data.points)} points")


@experiments_app.command("electrochem")
def electrochem(
    file: Annotated[
        Path,
        typer.Argument(help="A measurement file (cheme/electrochemical-measurements/v1)."),
    ],
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
    plot: Annotated[
        Path | None,
        typer.Option(help="Write the SVG figures the data support into this directory."),
    ] = None,
) -> None:
    """Process a measured electrochemical series: per replicate and point (mean, sd, n) the
    Faradaic efficiency of each product, partial current densities, the water dissociation
    efficiency from the anolyte titration, power, heat and the charge and carbon balances.
    Reads the file only (a plant repository is not needed); --plot writes polarisation,
    Faradaic efficiency, partial current density and water dissociation plots. Exit 1 on an
    error finding, 2 when the file does not exist."""
    from chemeascode.domains.experiments.electrochemistry import (
        measurement_plots,
        measurement_report,
        report_text,
    )
    from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

    if not file.is_file():
        typer.echo(f"{file} does not exist", err=True)
        raise typer.Exit(2)
    path = file.resolve()
    try:
        root = Workspace.find(path.parent).root
    except NotAPlantRepository:
        root = path.parent  # a measurement outside a plant repository: its folder
    report = measurement_report(root, path)
    typer.echo(report.to_json() if as_json else report_text(report))
    if plot is not None:
        plot.mkdir(parents=True, exist_ok=True)
        for name, svg in measurement_plots(report).items():
            (plot / name).write_text(svg, encoding="utf-8")
            if not as_json:
                typer.echo(f"wrote {plot / name}")
    if report.errors:
        raise typer.Exit(1)
