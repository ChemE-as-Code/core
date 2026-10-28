"""The OSHA Occupational Chemical Database (https://www.osha.gov/chemicaldata/): physical hazard
data, NFPA ratings and exposure limits of a chemical, read from its HTML pages.

LLM4ChemE drove a headless Chrome through Selenium; the pages are plain server-rendered HTML, so
this adapter reads them over HTTP and parses them with lxml, with the same table positions. The
database is searched by CAS number only. osha.gov answers HTTP 403 to non-browser clients
(checked 2026-10); the adapter sends its own User-Agent and does not pose as a browser, so with
the default client it fails with that message. A caller with another way to fetch the pages
passes a ``client`` with its own transport; the parsers (:func:`find_chemical_url`,
:func:`parse_chemical_page`) only need the HTML.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from lxml import html

from chemeascode.foundation.schema_base import CAS_RE
from chemeascode.integrations.http import HttpClient, HttpError, Response

BASE_URL = "https://www.osha.gov"
SEARCH_URL = "https://www.osha.gov/chemicaldata/search"
MAX_SEARCH_PAGES = 100

# Minus signs in the pages: hyphen, U+2212 minus, U+2013 en dash.
_MINUS = "-−–"
_NUMBER = rf"[{_MINUS}]?(?:[0-9]{{1,3}}(?:,[0-9]{{3}})+|[0-9]+)(?:\.[0-9]+)?"
# A temperature or a range sharing one unit: "-49°F", "103 °F", "300 K", "100-162°F",
# "-58--40°F", "-20 to -10 °F". The look-behind keeps a match from starting inside a word.
_TEMPERATURE_RE = re.compile(
    rf"(?<![\w.,])(?P<low>{_NUMBER})"
    rf"(?:\s*(?:[{_MINUS}]|to)\s*(?P<high>{_NUMBER}))?\s*"
    r"(?:(?P<degree>[°º˚]|deg(?:rees?)?\.?)\s*)?"
    r"(?P<unit>[FCK])\b"
)
# A grade label right before a number, as in "No. 2" fuel oil.
_GRADE_LABEL_RE = re.compile(r"\bNo\.?\s*$", re.IGNORECASE)
_TEMPERATURE_UNITS = {"F": "°F", "C": "°C", "K": "K"}
_WITH_UNITS = re.compile(r"(-?[0-9]+\.?[0-9]*)\s?([\%pbµmlg\/³3][\w/³²]*)")
_NUMERIC = re.compile(r"(-?[0-9]+\.?[0-9]*)")
_EXPOSURE = re.compile(r"([0-9]+\.?\,?[0-9]*)\s?([\w/³²µ]*)")

#: Physical-properties table: field -> (row, cell), 1-based, and how the cell is read.
_PHYSICAL = {
    "molecular_weight": (2, 2, "number"),
    "vapor_pressure": (3, 2, "mmHg"),
    "flash_point": (4, 1, "temperature"),
    "vapor_density": (4, 2, "number"),
    "specific_gravity": (5, 1, "number"),
    "lower_explosive_limit": (6, 1, "%"),
    "upper_explosive_limit": (6, 2, "%"),
    "nfpa_health_rating": (7, 1, "number"),
    "nfpa_fire_rating": (7, 2, "number"),
    "nfpa_reactivity_rating": (8, 1, "number"),
}
#: Exposure-limits table: field -> (row, cell).
_EXPOSURE_CELLS = {
    "osha_twa": (2, 1),
    "niosh_twa": (2, 2),
    "acgih_twa": (2, 3),
    "cal_osha_twa": (2, 4),
    "osha_stel": (3, 1),
    "niosh_stel": (3, 2),
    "acgih_stel": (3, 3),
    "cal_osha_stel": (3, 4),
    "idlh": (7, 2),
}


def _to_float(number: str) -> float:
    if number[0] in _MINUS:
        number = "-" + number[1:]
    return float(number.replace(",", ""))


def parse_temperature(text: str) -> dict | None:
    """A signed temperature (or range) and its unit from cell text.

    For a range ("100-162°F") the unit applies to both ends and ``value`` is the lower bound,
    the conservative choice for a flash point; ``range`` gives both. A number right after a grade
    label ("No. 2-4°F") is the label, so that text gives -4 °F. None without a recognisable unit.
    """
    for match in _TEMPERATURE_RE.finditer(text):
        unit = match.group("unit")
        if unit == "K" and match.group("degree"):  # kelvin has no degree sign
            continue
        if match.group("high") and _GRADE_LABEL_RE.search(text[: match.start()]):
            return parse_temperature(text[match.end("low") :])
        units = _TEMPERATURE_UNITS[unit]
        low = _to_float(match.group("low"))
        if not match.group("high"):
            return {"value": low, "units": units}
        low, high = sorted((low, _to_float(match.group("high"))))
        return {"value": low, "units": units, "range": [low, high]}
    return None


def _text(node) -> str:
    return " ".join(node.xpath("string(.)").split())


def find_chemical_url(search_page: str, cas: str) -> str | None:
    """The detail-page URL of *cas* on one search-results page, or None."""
    doc = html.fromstring(search_page)
    for row in doc.xpath("//table//tbody/tr"):
        cells = row.xpath(".//td[@class='views-field views-field-field-cas-number']")
        links = row.xpath(".//td[@class='views-field views-field-title']//a/@href")
        if not cells or not links:
            continue
        found = _text(cells[0])
        if found == cas or found.replace("-", "") == cas.replace("-", ""):
            return urljoin(BASE_URL, str(links[0]))
    return None


def _cell(table, row: int, cell: int) -> str:
    found = table.xpath(f".//tbody/tr[{row}]/td[{cell}]")
    return _text(found[0]) if found else ""


def _read(text: str, kind: str) -> Any:
    if not text:
        return None
    if kind == "temperature":
        return parse_temperature(text)
    if kind == "number":
        match = _NUMERIC.search(text)
        return float(match.group(1)) if match else None
    match = _WITH_UNITS.search(text)
    if match and match.group(1):
        return {"value": float(match.group(1)), "units": match.group(2) or kind}
    return None


def parse_chemical_page(page: str, url: str) -> dict[str, Any] | None:
    """The fields of a chemical's detail page (names as in :data:`_PHYSICAL` and
    :data:`_EXPOSURE_CELLS`, plus ``name``, ``cas``, ``source_url``); None if the page has no
    results block. A value with units is ``{"value": ..., "units": ...}``."""
    doc = html.fromstring(page)
    results = doc.xpath("//div[@id='chemResultTables']")
    if not results:
        return None
    names = results[0].xpath(".//h3/strong")
    if not names:
        return None
    name = re.sub(r"[^a-zA-Z0-9\s]", "", _text(names[0]))
    found: dict[str, Any] = {"name": name.lower(), "source_url": url}
    tables = {}
    for table in results[0].xpath(
        ".//div[@class='table-responsive dol-table']/table[@class='usa-table table']"
    ):
        caption = " ".join(table.xpath("string(.//caption//h4)").split())
        for key, label in (
            ("id", "Chemical Identification"),
            ("physical", "Physical Properties"),
            ("exposure", "Exposure Limits"),
        ):
            if label in caption:
                tables[key] = table
    if "id" in tables:
        found["cas"] = _cell(tables["id"], 1, 1) or None
    if "physical" in tables:
        for field, (row, cell, kind) in _PHYSICAL.items():
            value = _read(_cell(tables["physical"], row, cell), kind)
            if value is not None:
                found[field] = value
    if "exposure" in tables:
        for field, (row, cell) in _EXPOSURE_CELLS.items():
            match = _EXPOSURE.search(_cell(tables["exposure"], row, cell))
            if match and match.group(1):
                value = float(match.group(1).replace(",", ""))
                found[field] = {"value": value, "units": match.group(2) or "ppm"}
    return found


def _get(client: HttpClient, url: str, params: dict[str, Any] | None = None) -> Response:
    try:
        return client.get(url, params)
    except HttpError as failure:
        if failure.status != 403:
            raise
        raise HttpError(
            "osha.gov refused the request (HTTP 403): it serves browsers only and this adapter "
            "does not pose as one; pass a client whose transport can fetch its pages",
            url=failure.url,
            status=failure.status,
        ) from failure


def retrieve(cas: str, *, client: HttpClient | None = None) -> dict[str, Any] | None:
    """The OSHA data of the chemical with CAS number *cas*, or None if it is not listed.

    Walks the search pages (at most :data:`MAX_SEARCH_PAGES`) until a page has no rows; the
    first error status stops it (:class:`HttpError`). Raises ``ValueError`` when *cas* is no
    CAS number: a name would never match and would walk every page (resolve its CAS number
    first, e.g. PubChem's ``cas_rn``).
    """
    cas = cas.strip()
    if not CAS_RE.match(cas):
        raise ValueError(f"OSHA is searched by CAS number, and {cas!r} is none")
    client = client or HttpClient()
    for page in range(MAX_SEARCH_PAGES):
        listing = _get(client, SEARCH_URL, {"page": page}).text
        url = find_chemical_url(listing, cas)
        if url:
            return parse_chemical_page(_get(client, url).text, url)
        if not html.fromstring(listing).xpath("//table//tbody/tr"):
            return None
    return None
