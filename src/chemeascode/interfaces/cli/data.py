"""``cheme data``: optional datasets that cheme-as-code does not ship and a user installs into
the user data directory (foundation/userdata.py). Today the ChemSep SRK interaction
parameters (domains/process/thermodynamics/chemsep_srk.py, pre-release issue 55)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

data_app = typer.Typer(
    help="Optional datasets: fetch them into the user data directory.",
    no_args_is_help=True,
)

DATASETS = {
    "chemsep-srk": "ChemSep SRK binary interaction parameters (kij) from ChemSep-LITE ipd/srk.ipd",
}


@data_app.command("fetch")
def fetch(
    dataset: Annotated[str, typer.Argument(help=f"Dataset: {', '.join(DATASETS)}.")],
    zip_path: Annotated[
        Path | None,
        typer.Option(
            "--zip",
            help="A local ChemSep-LITE lite.zip (offline); without it the archive is downloaded.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    url: Annotated[str | None, typer.Option(help="Download from this URL instead.")] = None,
    sha256: Annotated[
        str | None,
        typer.Option(help="Expected sha256 of the archive (default: the recorded release)."),
    ] = None,
    no_verify: Annotated[
        bool, typer.Option("--no-verify", help="Do not check the archive's sha256.")
    ] = False,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            help="Install under this directory (default: $CHEME_DATA_DIR or the user "
            "data directory)."
        ),
    ] = None,
) -> None:
    """Download (or read with --zip) an optional dataset, check it and install it.

    chemsep-srk: ChemSep-LITE from http://www.chemsep.org/downloads/data/lite.zip (plain HTTP;
    the sha256 recorded for ChemSep-LITE 8.50 is checked), its ipd/srk.ipd converted to
    srk.json for the Redlich-Kwong-Soave flash. Its licence is not confirmed for
    redistribution (pre-release issue 55), so cheme-as-code does not ship it. Exits 2 on a failed
    check.
    """
    from chemeascode.domains.process.thermodynamics.chemsep_srk import (
        LITE_RELEASE,
        LITE_SHA256,
        LITE_URL,
        ChemSepDataError,
        fetch_srk,
    )
    from chemeascode.integrations.http import HttpError

    if dataset not in DATASETS:
        typer.echo(f"unknown dataset: {dataset}; known: {', '.join(DATASETS)}", err=True)
        raise typer.Exit(2)
    if no_verify and sha256:
        typer.echo("--sha256 and --no-verify exclude each other", err=True)
        raise typer.Exit(2)
    expected = None if no_verify else (sha256 or LITE_SHA256)
    if zip_path is None:
        typer.echo(f"downloading {url or LITE_URL} ...", err=True)
    try:
        installed = fetch_srk(
            zip_path=zip_path, url=url or LITE_URL, expected_sha256=expected, root=data_dir
        )
    except (ChemSepDataError, HttpError) as failure:
        typer.echo(f"error: {failure}", err=True)
        if zip_path is None and isinstance(failure, HttpError):
            typer.echo("hint: download lite.zip yourself and pass it with --zip <path>", err=True)
        raise typer.Exit(2) from failure
    checked = (
        f"sha256 {installed.archive_sha256} verified"
        + (f" ({LITE_RELEASE})" if expected == LITE_SHA256 else "")
        if installed.checksum_verified
        else f"sha256 {installed.archive_sha256} NOT verified (--no-verify)"
    )
    typer.echo(f"installed {dataset}: {installed.entries} pairs -> {installed.json_path}")
    typer.echo(f"from {installed.source} ({installed.member}); {checked}")


@data_app.command("status")
def status(
    data_dir: Annotated[
        Path | None, typer.Option(help="Look under this directory instead.")
    ] = None,
) -> None:
    """Which optional datasets are installed, and where."""
    from chemeascode.domains.process.thermodynamics.chemsep_srk import (
        FETCH_COMMAND,
        dataset_dir,
        installed_srk_json,
    )

    path = installed_srk_json(data_dir)
    if path is None:
        typer.echo(
            f"chemsep-srk: not installed (looked in {dataset_dir(data_dir)}); run `{FETCH_COMMAND}`"
        )
    else:
        typer.echo(f"chemsep-srk: installed at {path}")
