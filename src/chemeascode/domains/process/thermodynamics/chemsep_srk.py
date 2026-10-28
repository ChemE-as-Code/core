"""The ChemSep SRK binary interaction parameters (``kij``): an optional, user-fetched dataset.

cheme-as-code does not ship ChemSep's ``srk.ipd`` ("DECHEMA Soave-Redlich-Kwong Parameters")
while its licence is unconfirmed (pre-release issue 55; ``data/chemsep/SOURCE.md``). ``cheme data
fetch chemsep-srk`` downloads ChemSep-LITE (or reads a local copy of the archive), checks its
sha256, takes ``ipd/srk.ipd`` and converts it with :func:`parse_srk_ipd` into ``srk.json`` in the
user data directory (:func:`chemeascode.foundation.userdata.user_data_dir`, ``chemsep/``). The flash
of ``thermodynamics.phase`` reads it from there and uses ``kij = 0`` when it is absent.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from chemeascode.foundation.userdata import user_data_dir

LITE_URL = "http://www.chemsep.org/downloads/data/lite.zip"
#: sha256 of ChemSep-LITE 8.50 ``lite.zip`` as downloaded on 2026-10-23 (12 032 722 bytes).
LITE_SHA256 = "69640c709f51ef89341ff1596b4fea4a37d9de774f4fac041934c0413958573c"
LITE_RELEASE = "ChemSep-LITE 8.50"
IPD_MEMBER = "ipd/srk.ipd"
LICENSE_MEMBER = "pcd/Artistic_license_2_0.txt"
FETCH_COMMAND = "cheme data fetch chemsep-srk"
DATASET = "chemsep-srk"
#: A member larger than this is not an interaction parameter file (a guard against zip bombs).
_MAX_MEMBER_BYTES = 10 * 1024 * 1024


class ChemSepDataError(ValueError):
    """The archive is not the expected one or holds no usable ``srk.ipd``."""


@dataclass(frozen=True)
class SrkInstall:
    """Where the dataset was written and what it came from."""

    json_path: Path
    entries: int
    source: str
    archive_sha256: str
    checksum_verified: bool
    member: str


def dataset_dir(root: Path | None = None) -> Path:
    """``<user data dir>/chemsep`` (or ``<root>/chemsep``)."""
    return (root if root is not None else user_data_dir()) / "chemsep"


def installed_srk_json(root: Path | None = None) -> Path | None:
    """The fetched ``srk.json``, or None when ``cheme data fetch chemsep-srk`` has not run."""
    path = dataset_dir(root) / "srk.json"
    return path if path.is_file() else None


def missing_srk_message() -> str:
    return (
        "ChemSep SRK interaction parameters are not installed; kij = 0 is used for every pair "
        f"(Redlich-Kwong-Soave). Run `{FETCH_COMMAND}` to install them "
        f"(looked in {dataset_dir()})."
    )


def _cas_number(cas: str) -> int:
    """thermo's sort key of a CAS number (``chemicals.utils.CAS2int``); a malformed one last."""
    try:
        return int(cas.replace("-", ""))
    except ValueError:
        return 10**12


def parse_srk_ipd(text: str, eos_type: str = "SRK") -> dict[str, Any]:
    """A ChemSep ``.ipd`` file of ``kij`` as the JSON layout thermo's
    ``InteractionParameterDB.load_json`` reads (that of thermo's ChemSep ``pr.json``).

    Ported unchanged in its results from LLM4ChemE's ``src/data/convert_srk_to_json.py``: rows
    after ``[IPD]`` as ``CAS1 CAS2 kij comment``; ``Tmin`` from ``T=a-bK`` or ``T=aK``,
    ``Pmin``/``Pmax`` or ``P`` from ``P=...bar``, the DECHEMA page from ``p<n>``. A pair listed
    twice keeps its last row.

    One change: the key is the CAS pair in thermo's sorted order (by the CAS number as an
    integer), because the table is marked symmetric and thermo looks a symmetric pair up by its
    sorted key; about half of ChemSep's rows list the larger CAS number first. (The ``srk.json``
    bundled before pre-release issue 55 was marked asymmetric instead, so its ``kij`` depended on
    the order of the components.)
    """
    data: dict[str, dict[str, Any]] = {}
    in_data = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[IPD]":
            in_data = True
            continue
        if line.startswith("Comment=") or not in_data:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            kij = float(parts[2])
        except ValueError:
            continue
        comment = " ".join(parts[3:])
        tmin = p = pmin = pmax = None
        match = re.search(r"T=([\d.]+)-([\d.]+)K?", comment) or re.search(r"T=([\d.]+)K?", comment)
        if match:
            tmin = float(match.group(1))
        match = re.search(r"P=([\d.]+)-([\d.]+)bar", comment)
        if match:
            pmin, pmax = float(match.group(1)), float(match.group(2))
        else:
            match = re.search(r"P=([\d.]+)bar", comment)
            if match:
                p = float(match.group(1))
        match = re.search(r"p(\d+)", comment)
        page = [f"p{match.group(1)}"] if match else []
        pair = sorted(parts[:2], key=_cas_number)
        data[" ".join(pair)] = {
            "Tmin": tmin,
            "P": p,
            "Pmin": pmin,
            "kij": kij,
            "T": None,
            "page": page,
            "Pmax": pmax,
        }
    metadata = {
        "symmetric": True,
        "source": "ChemSep",
        "components": 2,
        "necessary keys": ["kij"],
        "P dependent": False,
        "missing": {"kij": 0},
        "type": f"{eos_type} kij",
        "T dependent": False,
    }
    return {"data": data, "metadata": metadata}


def srk_json_text(ipd_text: str) -> str:
    """:func:`parse_srk_ipd` serialised compactly, as LLM4ChemE wrote ``srk.json``."""
    return json.dumps(parse_srk_ipd(ipd_text), indent=None, separators=(",", ":"))


def _member(archive: zipfile.ZipFile, name: str) -> zipfile.ZipInfo | None:
    """The member ``name`` at the top or under the release folder (``Program Files/
    ChemSepL8v50/ipd/srk.ipd`` in ChemSep-LITE 8.50), matched case-insensitively."""
    wanted = name.lower()
    found = [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and (info.filename.lower() == wanted or info.filename.lower().endswith("/" + wanted))
    ]
    if len(found) > 1:
        names = ", ".join(info.filename for info in found)
        raise ChemSepDataError(f"the archive holds {name} more than once: {names}")
    return found[0] if found else None


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > _MAX_MEMBER_BYTES:
        raise ChemSepDataError(f"{info.filename} is larger than {_MAX_MEMBER_BYTES} bytes")
    return archive.read(info)


def _write(path: Path, content: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def install_srk(
    archive_bytes: bytes,
    *,
    source: str,
    expected_sha256: str | None = LITE_SHA256,
    root: Path | None = None,
) -> SrkInstall:
    """Check *archive_bytes* (a ChemSep-LITE zip) against *expected_sha256* (None: no check),
    convert its ``ipd/srk.ipd`` and write ``srk.ipd``, ``srk.json``, the Artistic License copy
    when the archive has one, and ``SOURCE.json`` to :func:`dataset_dir`. Raises
    :class:`ChemSepDataError` and writes nothing when a check fails."""
    digest = hashlib.sha256(archive_bytes).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ChemSepDataError(
            f"{source}: sha256 {digest} is not the recorded {expected_sha256} "
            f"({LITE_RELEASE}). A different ChemSep release: check it and pass its sha256 "
            "with --sha256, or --no-verify."
        )
    try:
        archive = zipfile.ZipFile(BytesIO(archive_bytes))
    except zipfile.BadZipFile as failure:
        raise ChemSepDataError(f"{source}: not a zip archive ({failure})") from None
    with archive:
        info = _member(archive, IPD_MEMBER)
        if info is None:
            raise ChemSepDataError(f"{source}: no {IPD_MEMBER} in the archive")
        ipd = _read(archive, info)
        licence_info = _member(archive, LICENSE_MEMBER)
        licence = _read(archive, licence_info) if licence_info is not None else None
    text = ipd.decode("latin-1")
    converted = srk_json_text(text)
    entries = len(json.loads(converted)["data"])
    if entries == 0:
        raise ChemSepDataError(f"{source}: {info.filename} holds no kij rows")
    target = dataset_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    _write(target / "srk.ipd", ipd)
    if licence is not None:
        _write(target / "Artistic_license_2_0.txt", licence)
    record = {
        "dataset": DATASET,
        "source": source,
        "member": info.filename,
        "archive_sha256": digest,
        "checksum_verified": expected_sha256 is not None,
        "recorded_release": LITE_RELEASE,
        "recorded_sha256": LITE_SHA256,
        "entries": entries,
        "fetched": datetime.now(UTC).isoformat(timespec="seconds"),
        "converter": "chemeascode.domains.process.thermodynamics.chemsep_srk.parse_srk_ipd",
        "note": (
            "srk.json is a modified version of ChemSep's srk.ipd (converted to JSON). "
            "Licence: see cheme-as-code data/chemsep/SOURCE.md (pre-release issue 55)."
        ),
    }
    _write(target / "SOURCE.json", (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    json_path = target / "srk.json"
    _write(json_path, converted.encode("utf-8"))
    return SrkInstall(
        json_path=json_path,
        entries=entries,
        source=source,
        archive_sha256=digest,
        checksum_verified=expected_sha256 is not None,
        member=info.filename,
    )


def fetch_srk(
    *,
    zip_path: Path | None = None,
    url: str = LITE_URL,
    expected_sha256: str | None = LITE_SHA256,
    root: Path | None = None,
    download: Callable[[str], bytes] | None = None,
) -> SrkInstall:
    """Install the dataset from *zip_path* (offline) or by downloading *url*.

    *download* defaults to :func:`chemeascode.integrations.chemsep.download`; it raises
    ``integrations.http.HttpError`` when the download fails.
    """
    if zip_path is not None:
        try:
            archive = Path(zip_path).read_bytes()
        except OSError as failure:
            raise ChemSepDataError(f"{zip_path}: {failure.strerror or failure}") from None
        source = str(zip_path)
    else:
        if download is None:
            from chemeascode.integrations.chemsep import download as fetch_url

            download = fetch_url
        archive = download(url)
        source = url
    return install_srk(archive, source=source, expected_sha256=expected_sha256, root=root)
