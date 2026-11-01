"""Build a grid-electricity factor file on ONE declared basis from your own copy of Ember's data.

Usage::

    uv run python scripts/build_grid_profile.py ember-yearly-long.csv --year 2025 \\
        --release "release of 2026-09-15" --downloaded 2026-10-26 \\
        --countries DE NL GB [--output lca/grid-ember.yaml]

``CSV`` is Ember's "Yearly electricity data, long format"
(https://ember-energy.org/data/yearly-electricity-data/, CC BY 4.0), downloaded by you. The file
is read, never copied into the package: the output is a factor file (``lca_factors``) for your
project, to be used as its ``lca/factors.yaml`` or merged into it. It records the source, the
release you name, the licence, the attribution and the SHA-256 of your copy, so the numbers can
be traced to the exact download.

One basis for every country. Only the rows ``Power sector emissions``
/ ``CO2 intensity`` in ``gCO2/kWh`` of an economy are read. Their scope, declared on the source
and so on every factor: ``basis: direct`` (emissions at the power plants, no upstream),
``gases: co2`` (CO2 only, no CH4 or N2O), ``accounting: generation`` (the economy's own
generation, no trade adjustment), ``delivery: generation`` (per kWh generated, no T&D losses),
``mix: grid-average``. The values are therefore comparable among themselves (like-for-like),
and they are **not comparable** with a CO2e or a life-cycle profile (the packaged ``ember-2025``
is life-cycle CO2e; DESNZ is at the consumer): core flags that from the scope.
Each factor sets ``data_year`` to the year of the data; ``publication_year`` only with
``--publication-year``.

Nothing is guessed: an economy absent from the file, without a value for the year, or with a
non-numeric value is listed and left out. The values stay as Ember publishes them (the latest
year is partly estimated and revised in later releases, by Ember's account).

Not read here: the EEA ENER038 indicator, the US EPA eGRID, the UBA mix and the Dutch CBS
series. Their files, terms or bases have not been checked for this script, so no reader exists
for them (docs/framework/lci-comparison-basis.md lists what is open).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

import yaml

SOURCE_ID = "ember-direct-co2"
URL = "https://ember-energy.org/data/yearly-electricity-data/"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
CATEGORY = "Power sector emissions"
VARIABLE = "CO2 intensity"
UNIT = "gCO2/kWh"
REQUIRED = {"Area", "ISO 3 code", "Year", "Area type", "Category", "Variable", "Unit", "Value"}

#: ISO 3166-1 alpha-3 to alpha-2 for the economies of the packaged profiles (G20, EU-27, NO, CH).
ISO2 = {
    "ARG": "AR", "AUS": "AU", "AUT": "AT", "BEL": "BE", "BGR": "BG", "BRA": "BR", "CAN": "CA",
    "CHE": "CH", "CHN": "CN", "CYP": "CY", "CZE": "CZ", "DEU": "DE", "DNK": "DK", "ESP": "ES",
    "EST": "EE", "FIN": "FI", "FRA": "FR", "GBR": "GB", "GRC": "GR", "HRV": "HR", "HUN": "HU",
    "IDN": "ID", "IND": "IN", "IRL": "IE", "ITA": "IT", "JPN": "JP", "KOR": "KR", "LTU": "LT",
    "LUX": "LU", "LVA": "LV", "MEX": "MX", "MLT": "MT", "NLD": "NL", "NOR": "NO", "POL": "PL",
    "PRT": "PT", "ROU": "RO", "RUS": "RU", "SAU": "SA", "SVK": "SK", "SVN": "SI", "SWE": "SE",
    "TUR": "TR", "USA": "US", "ZAF": "ZA",
}  # fmt: skip


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_intensities(path: Path, year: int) -> tuple[dict[str, tuple[str, float, int]], list[str]]:
    """``{ISO2: (area name, kg CO2 per kWh, CSV line)}`` for *year*, and what could not be read.

    Raises ``ValueError`` when the file is not Ember's long format (a column is missing)."""
    found: dict[str, tuple[str, float, int]] = {}
    skipped: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path.name} is not Ember's long format: missing column(s) {sorted(missing)}"
            )
        for row in reader:
            if (row["Category"], row["Variable"]) != (CATEGORY, VARIABLE):
                continue
            if row["Area type"] != "Country or economy" or row["Year"] != str(year):
                continue
            if row["Unit"] != UNIT:
                raise ValueError(
                    f"line {reader.line_num}: unit {row['Unit']!r}, expected {UNIT!r}; "
                    "the file's definition changed, check it before reading"
                )
            iso3 = row["ISO 3 code"]
            try:
                grams = float(row["Value"])
            except ValueError:
                skipped.append(f"{row['Area']} ({iso3}): value {row['Value']!r} is not a number")
                continue
            if grams < 0:
                skipped.append(f"{row['Area']} ({iso3}): negative value {grams}")
                continue
            if iso3 not in ISO2:
                continue
            found[ISO2[iso3]] = (row["Area"], round(grams / 1000, 6), reader.line_num)
    return found, skipped


def build(
    csv_path: Path,
    year: int,
    countries: list[str] | None,
    release: str,
    downloaded: str,
    publication_year: int | None,
) -> tuple[dict, list[str]]:
    """The factor file as a dict, and the notes on what was left out."""
    found, notes = read_intensities(csv_path, year)
    wanted = [c.upper() for c in countries] if countries else sorted(found)
    unknown = [c for c in wanted if c not in ISO2.values()]
    if unknown:
        raise ValueError(f"not in the country table: {', '.join(unknown)}")
    factors = []
    for iso2 in wanted:
        if iso2 not in found:
            notes.append(f"{iso2}: no {VARIABLE} for {year} in the file")
            continue
        name, kg, line = found[iso2]
        factor = {
            "id": f"electricity-{iso2.lower()}",
            "title": f"Electricity, {name}, gross generation (direct CO2)",
            "unit": "kWh",
            "values": {"climate-change": kg},
            "status": "PUBLISHED",
            "source": (
                f"Ember yearly electricity data (long format), line {line} ({name}, {year}, "
                f"{CATEGORY}, {VARIABLE}) = {kg * 1000:g} {UNIT}"
            ),
            "source_id": SOURCE_ID,
            "year": year,
            "data_year": year,
            "location": iso2,
        }
        if publication_year is not None:
            factor["publication_year"] = publication_year
        factors.append(factor)
    if not factors:
        raise ValueError("no factor could be built")
    source = {
        "id": SOURCE_ID,
        "title": "Ember Yearly Electricity Data (long format): CO2 intensity of the power sector",
        "provider": "Ember",
        "version": f"{release} (downloaded {downloaded}), data year {year}",
        "url": URL,
        "licence": "CC-BY-4.0",
        "attribution": (
            f"Ember (Yearly Electricity Data, {release}), {URL}, CC BY 4.0 ({LICENCE_URL}); "
            "subset, converted to kg CO2/kWh."
        ),
        "publication": "public",
        "redistribution": True,
        "geography": "GLO",
        "year": year,
        "method": "direct CO2 of the power sector per kWh of generation (Ember)",
        "checksum": f"sha256:{sha256(csv_path)}",
        "scope": {
            "basis": "direct",
            "gases": "co2",
            "accounting": "generation",
            "delivery": "generation",
            "mix": "grid-average",
            "note": (
                "CO2 only, emissions at the power plants, no upstream, no T&D losses, no trade "
                "adjustment; the latest year may be partly estimated and is revised in later "
                "releases (Ember)."
            ),
        },
        "notes": (
            "Built by scripts/build_grid_profile.py from the download whose SHA-256 is the "
            "checksum; the URL is not versioned."
        ),
    }
    data = {
        "schema": "cheme/lca/v1",
        "kind": "lca_factors",
        "sources": [source],
        "categories": [
            {
                "id": "climate-change",
                "title": "Climate change",
                "unit": "kg CO2-eq",
                "method": "direct CO2 only (Ember); no CH4 or N2O",
            }
        ],
        "factors": factors,
    }
    return data, notes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("csv", type=Path, help="Ember yearly electricity data, long format (CSV)")
    p.add_argument("--year", type=int, required=True, help="the data year to read")
    p.add_argument("--release", required=True, help="Ember's release label, e.g. 'release of ...'")
    p.add_argument("--downloaded", required=True, help="date you downloaded the file (YYYY-MM-DD)")
    p.add_argument("--publication-year", type=int, help="year of the release (optional)")
    p.add_argument("--countries", nargs="*", help="ISO 3166-1 alpha-2 codes (default: all known)")
    p.add_argument("--output", type=Path, help="write here (default: print)")
    args = p.parse_args(argv)
    try:
        data, notes = build(
            args.csv,
            args.year,
            args.countries,
            args.release,
            args.downloaded,
            args.publication_year,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = (
        "# Built by scripts/build_grid_profile.py from Ember data (CC-BY-4.0):\n"
        "# direct CO2 per kWh of generation, one basis for every country. Credit Ember with the\n"
        "# attribution of the source below. Not comparable with CO2e or life-cycle factors.\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    )
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}: {len(data['factors'])} factor(s)")
    else:
        print(text, end="")
    for note in notes:
        print(f"left out: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
