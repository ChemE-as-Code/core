"""The optional ChemSep SRK dataset: conversion, install from a zip, the CLI
and the kij = 0 fallback of the flash. No test touches the network: archives are built here."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from chemeascode.domains.process.thermodynamics import chemsep_srk
from chemeascode.domains.process.thermodynamics.chemsep_srk import (
    ChemSepDataError,
    fetch_srk,
    install_srk,
    installed_srk_json,
    parse_srk_ipd,
)
from chemeascode.foundation.userdata import user_data_dir
from chemeascode.interfaces.cli import app

runner = CliRunner()

IPD = (
    " ---------------------------------------------\r\n"
    "             ===  ChemSep ===\r\n"
    " Copyright 2009 Harry Kooijman and Ross Taylor\r\n"
    "      Interaction Parameters Data (IPD)\r\n"
    " ---------------------------------------------\r\n"
    " Data: ID1  ID2  k12  comments\r\n"
    "[IPD]\r\n"
    "Comment=DECHEMA Soave-Redlich-Kwong EOS data\r\n"
    "#\r\n"
    "# ID/CASN       ID/CASN    k12      Name/Name Comments\r\n"
    "7440-59-7       630-08-0   .6507    Helium-4/Carbon Monoxide p203\r\n"
    "1333-74-0       7727-37-9  .563e-1  Hydrogen/Nitrogen T=90-113K p210\r\n"
    "1333-74-0       7727-37-9  .1133    Hydrogen/Nitrogen T=77.35K p213\r\n"
    "7664-41-7       7732-18-5  -.2319   Ammonia/Water P=1.015bar p693\r\n"
    "74-82-8         74-84-0    .1      Methane/Ethane P=10-20bar p1\r\n"
    "67-56-1         7732-18-5  -.789e-1 Methanol/Water p730\r\n"
    "not-a-row\r\n"
)
LICENCE = b"The Artistic License 2.0 (test copy)\n"


def lite_zip(ipd: str = IPD, folder: str = "Program Files/ChemSepL8v50/") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(folder + "ipd/srk.ipd", ipd.encode("latin-1"))
        archive.writestr(folder + "ipd/pr.ipd", "unrelated")
        archive.writestr(folder + "pcd/Artistic_license_2_0.txt", LICENCE)
    return buffer.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_parse_keeps_llm4cheme_fields_and_sorts_pairs() -> None:
    table = parse_srk_ipd(IPD)
    data = table["data"]
    assert table["metadata"]["symmetric"] is True
    assert table["metadata"]["type"] == "SRK kij"
    assert table["metadata"]["missing"] == {"kij": 0}
    # the larger CAS number listed first is stored in thermo's sorted order
    assert "630-08-0 7440-59-7" in data and "7440-59-7 630-08-0" not in data
    assert data["630-08-0 7440-59-7"]["kij"] == pytest.approx(0.6507)
    # a pair listed twice keeps its last row
    assert data["1333-74-0 7727-37-9"] == {
        "Tmin": 77.35,
        "P": None,
        "Pmin": None,
        "kij": 0.1133,
        "T": None,
        "page": ["p213"],
        "Pmax": None,
    }
    assert data["7664-41-7 7732-18-5"]["P"] == pytest.approx(1.015)
    assert (data["74-82-8 74-84-0"]["Pmin"], data["74-82-8 74-84-0"]["Pmax"]) == (10.0, 20.0)
    assert len(data) == 5


def test_install_from_zip_writes_dataset(tmp_path: Path) -> None:
    archive = lite_zip()
    installed = install_srk(archive, source="t.zip", expected_sha256=sha(archive), root=tmp_path)
    folder = tmp_path / "chemsep"
    assert installed.json_path == folder / "srk.json"
    assert installed.entries == 5 and installed.checksum_verified
    assert installed.member == "Program Files/ChemSepL8v50/ipd/srk.ipd"
    assert json.loads(installed.json_path.read_text())["data"]["67-56-1 7732-18-5"]["kij"] == (
        pytest.approx(-0.0789)
    )
    assert (folder / "srk.ipd").read_bytes() == IPD.encode("latin-1")
    assert (folder / "Artistic_license_2_0.txt").read_bytes() == LICENCE
    record = json.loads((folder / "SOURCE.json").read_text())
    assert record["archive_sha256"] == sha(archive) and record["source"] == "t.zip"
    assert installed_srk_json(tmp_path) == installed.json_path


def test_checksum_mismatch_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ChemSepDataError, match="sha256"):
        install_srk(lite_zip(), source="t.zip", root=tmp_path)  # the recorded 8.50 checksum
    assert not (tmp_path / "chemsep").exists()
    assert installed_srk_json(tmp_path) is None


def test_archive_without_srk_or_not_a_zip(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ipd/pr.ipd", "x")
    with pytest.raises(ChemSepDataError, match="no ipd/srk.ipd"):
        install_srk(buffer.getvalue(), source="t.zip", expected_sha256=None, root=tmp_path)
    with pytest.raises(ChemSepDataError, match="not a zip"):
        install_srk(b"<html>", source="u", expected_sha256=None, root=tmp_path)
    with pytest.raises(ChemSepDataError, match="no kij rows"):
        install_srk(lite_zip("[IPD]\n"), source="t.zip", expected_sha256=None, root=tmp_path)


def test_fetch_downloads_through_injected_function(tmp_path: Path) -> None:
    archive = lite_zip(folder="")
    asked: list[str] = []

    def download(url: str) -> bytes:
        asked.append(url)
        return archive

    installed = fetch_srk(expected_sha256=sha(archive), root=tmp_path, download=download)
    assert asked == [chemsep_srk.LITE_URL]
    assert installed.source == chemsep_srk.LITE_URL and installed.member == "ipd/srk.ipd"


def test_user_data_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHEME_DATA_DIR", str(tmp_path))
    assert user_data_dir() == tmp_path
    monkeypatch.delenv("CHEME_DATA_DIR")
    assert user_data_dir().name == "cheme-as-code"


def test_cli_fetch_from_local_zip_and_status(tmp_path: Path) -> None:
    archive = lite_zip()
    path = tmp_path / "lite.zip"
    path.write_bytes(archive)
    result = runner.invoke(app, ["data", "status"])
    assert result.exit_code == 0 and "not installed" in result.output
    assert "cheme data fetch chemsep-srk" in result.output

    # the recorded checksum is that of the real 8.50 archive: a test archive is refused
    result = runner.invoke(app, ["data", "fetch", "chemsep-srk", "--zip", str(path)])
    assert result.exit_code == 2 and "sha256" in result.output

    result = runner.invoke(
        app, ["data", "fetch", "chemsep-srk", "--zip", str(path), "--sha256", sha(archive)]
    )
    assert result.exit_code == 0, result.output
    assert "installed chemsep-srk: 5 pairs" in result.output and "verified" in result.output
    target = Path(os.environ["CHEME_DATA_DIR"]) / "chemsep" / "srk.json"
    assert target.is_file()
    result = runner.invoke(app, ["data", "status"])
    assert "installed at" in result.output

    result = runner.invoke(
        app,
        [
            "data",
            "fetch",
            "chemsep-srk",
            "--zip",
            str(path),
            "--no-verify",
            "--data-dir",
            str(tmp_path / "other"),
        ],
    )
    assert result.exit_code == 0 and "NOT verified" in result.output
    assert (tmp_path / "other" / "chemsep" / "srk.json").is_file()


def test_cli_refuses_unknown_dataset_and_conflicting_options(tmp_path: Path) -> None:
    assert runner.invoke(app, ["data", "fetch", "nope"]).exit_code == 2
    result = runner.invoke(app, ["data", "fetch", "chemsep-srk", "--sha256", "ab", "--no-verify"])
    assert result.exit_code == 2


# -- the flash: fallback without the dataset, the dataset when installed ----------------------


def _srk_flash():
    from chemeascode.domains.process.thermodynamics.phase import EOSModel, phase_determination

    return phase_determination(
        components=["methanol", "water"],
        overall_composition=[0.5, 0.5],
        temperature_value=298.15,
        temperature_unit="K",
        pressure_value=101325,
        pressure_unit="Pa",
        thermodynamic_model=EOSModel(eos_model="Redlich-Kwong-Soave"),
        allow_two_liquids=False,
    )


def test_srk_without_dataset_uses_zero_kij_with_note() -> None:
    pytest.importorskip("thermo")
    from chemeascode.domains.process.thermodynamics.phase import (
        MissingInteractionParametersWarning,
    )

    with pytest.warns(MissingInteractionParametersWarning, match="cheme data fetch chemsep-srk"):
        result = _srk_flash()
    assert result.liquid_count == 1
    assert len(result.notes) == 1 and "kij = 0" in result.notes[0]


def test_srk_kij_from_installed_dataset_in_either_order() -> None:
    pytest.importorskip("thermo")
    from chemeascode.domains.process.thermodynamics.phase import EOSHandler

    archive = lite_zip()
    install_srk(archive, source="t.zip", expected_sha256=sha(archive))

    class Constants:
        CASs: ClassVar[list[str]] = ["7732-18-5", "67-56-1"]

    handler = EOSHandler("Redlich-Kwong-Soave")
    kijs = handler.interaction_parameters(Constants)
    assert kijs[0][1] == kijs[1][0] == pytest.approx(-0.0789)
    Constants.CASs = ["7440-59-7", "630-08-0"]  # listed in this order in the file
    assert handler.interaction_parameters(Constants)[0][1] == pytest.approx(0.6507)
    assert handler.notes == []
    result = _srk_flash()
    assert result.notes == [] and result.liquid_count == 1
