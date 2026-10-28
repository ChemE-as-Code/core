"""The NIST Chemistry WebBook (https://webbook.nist.gov): thermochemistry and phase-change data
of a compound, read from its HTML pages in SI units.

A lookup reads the compound page, then follows the links to the gas-phase thermochemistry,
condensed-phase thermochemistry and phase-change pages that exist. Parsing works on the HTML
(:func:`parse_pages`), so it is tested without the network.
"""

from __future__ import annotations

import contextlib
from urllib.parse import quote_plus, urljoin

from lxml import html
from pydantic import BaseModel, ConfigDict, Field

from chemeascode.foundation.schema_base import CAS_RE
from chemeascode.integrations.http import HttpClient, HttpError

WEBBOOK_URL = "https://webbook.nist.gov/cgi/cbook.cgi"


class ValueWithUnits(BaseModel):
    value: float
    units: str | None = None


class ShomateParameters(BaseModel):
    """Shomate heat-capacity equation for one temperature range (K)."""

    temperatures: tuple[float, float]
    A: float
    B: float
    C: float
    D: float
    E: float
    F: float
    G: float
    H: float


class AntoineParameters(BaseModel):
    """``log10(P/bar) = A - B/(T/K + C)`` over *temperatures* (K), as the WebBook gives it."""

    temperatures: tuple[float, float]
    A: float
    B: float
    C: float


class NISTThermodynamicProperties(BaseModel):
    """What the WebBook pages of one compound give. Values carry the WebBook's (SI) units."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = ""
    cas: str | None = None
    formula: str | None = None
    molecular_weight: float | None = Field(default=None, description="g/mol")
    iupac_std_inchi: str | None = None
    iupac_std_inchikey: str | None = None
    image: str | None = None
    source_url: str | None = Field(default=None, description="The compound page read")

    enthalpy_formation_gas: ValueWithUnits | None = None
    enthalpy_combustion_gas: ValueWithUnits | None = None
    entropy_gas: ValueWithUnits | None = None
    heat_capacity_shomate_equation_gas: list[ShomateParameters] | None = None

    enthalpy_formation_liquid: ValueWithUnits | None = None
    enthalpy_combustion_liquid: ValueWithUnits | None = None
    entropy_liquid: ValueWithUnits | None = None
    heat_capacity_shomate_equation_liquid: list[ShomateParameters] | None = None

    temperature_boil: ValueWithUnits | None = None
    temperature_fusion: ValueWithUnits | None = None
    temperature_triple: ValueWithUnits | None = None
    pressure_triple: ValueWithUnits | None = None
    temperature_critical: ValueWithUnits | None = None
    pressure_critical: ValueWithUnits | None = None
    volume_critical: ValueWithUnits | None = None
    density_critical: ValueWithUnits | None = None

    enthalpy_vaporization_average: ValueWithUnits | None = None
    enthalpy_vaporization_values: list[tuple[float, float]] | None = Field(
        default=None, description="(value, temperature) pairs, sorted by temperature"
    )
    enthalpy_vaporization_units: tuple[str, str] | None = None
    antoine_equation: list[AntoineParameters] | None = None


def to_float(text: str) -> float:
    """``"-74.87 ± 0.34"`` -> -74.87, ``"1.2×10-3"`` -> 0.0012."""
    text = text.strip().split(" ")[0]
    if "×10" in text:
        base, exponent = text.split("×10")
        return float(base) * 10 ** int(exponent)
    return float(text)


def _first(node, xpath: str) -> str | None:
    found = node.xpath(xpath)
    if isinstance(found, str):
        return found or None
    return str(found[0]) if found else None


_ONE_D_KEYS = {
    "Tboil": "temperature_boil",
    "Tfus": "temperature_fusion",
    "Ttriple": "temperature_triple",
    "Ptriple": "pressure_triple",
    "Tc": "temperature_critical",
    "Pc": "pressure_critical",
    "Vc": "volume_critical",
    "ρc": "density_critical",
    "ΔvapH°": "enthalpy_vaporization_average",
}


def parse_compound_page(page: str, url: str) -> tuple[dict, dict[str, str]]:
    """The identifiers on a compound page, and the absolute links to its data pages
    (``gas``, ``condensed``, ``phase``) that exist. Empty dict when the page has no compound."""
    doc = html.fromstring(page)
    name = _first(doc, "//h1[@id='Top']/text()")
    if not name:
        return {}, {}
    found: dict = {"name": name.strip().lower(), "source_url": url}
    cas = _first(doc, "//main/ul/li[strong[contains(string(.), 'CAS')]]/text()")
    if cas and cas.strip():
        found["cas"] = cas.strip()
    formula = _first(doc, "string(//main/ul/li[strong[contains(string(.), 'Formula')]])")
    if formula:
        found["formula"] = formula.replace("Formula:", "").strip()
    weight = _first(doc, "string(//main/ul/li[strong[contains(string(.), 'Molecular')]])")
    if weight:
        with contextlib.suppress(ValueError):
            found["molecular_weight"] = float(weight.split(":", 1)[-1].strip())
    inchi = _first(
        doc, "//main//span[@class='inchi-text' and starts-with(text(), 'InChI=')]/text()"
    )
    if inchi:
        found["iupac_std_inchi"] = inchi
    key = _first(
        doc, "//main//span[@class='inchi-text' and not(starts-with(text(), 'InChI='))]/text()"
    )
    if key:
        found["iupac_std_inchikey"] = key
    image = _first(doc, "//main//li[strong[contains(text(), 'Chemical structure')]]/img/@src")
    if image:
        found["image"] = urljoin(url, image)
    links = {}
    for kind, label in (
        ("gas", "Gas Phase Thermochemistry"),
        ("condensed", "Condensed Phase Thermochemistry"),
        ("phase", "Phase change data"),
    ):
        href = _first(doc, f"//main//li/a[contains(text(), '{label}')]/@href")
        if href:
            links[kind] = urljoin(url, href)
    return found, links


def parse_data_page(page: str, phase: str, found: dict) -> None:
    """Add what a data page gives to *found*. *phase* is ``gas``, ``liquid`` or ``""`` (the
    phase-change page)."""
    doc = html.fromstring(page)
    keys = {
        **_ONE_D_KEYS,
        f"ΔfH°{phase}": f"enthalpy_formation_{phase}",
        f"ΔcH°{phase}": f"enthalpy_combustion_{phase}",
        f"S°{phase}": f"entropy_{phase}",
    }
    for row in doc.xpath("//table[@aria-label='One dimensional data']//tr[td]"):
        label = row.xpath("string(td[1])").strip()
        value = row.xpath("string(td[2])").strip()
        if label in keys and value and keys[label] not in found:
            try:
                found[keys[label]] = {
                    "value": to_float(value),
                    "units": row.xpath("string(td[3])").strip(),
                }
            except ValueError:
                continue
    if phase:
        _shomate(doc, phase, found)
    if phase in ("", "liquid"):
        _vaporization(doc, found)
        _antoine(doc, found)


def _shomate(doc, phase: str, found: dict) -> None:
    label = f"{phase.capitalize()} Phase Heat Capacity (Shomate Equation)"
    tables = doc.xpath(f"//table[@aria-label='{label}']")
    if not tables:
        return
    table = tables[0]
    ranges = table.xpath(".//tr[1]/td/text()")
    rows = table.xpath(".//tr[position() > 1 and position() < 10]")
    sets = []
    for i, span in enumerate(ranges):
        try:
            low, high = (float(t) for t in span.split("-"))
            values = {
                letter: to_float(rows[j].xpath(f"string(td[{i + 1}])"))
                for j, letter in enumerate("ABCDEFGH")
            }
        except (ValueError, IndexError):
            continue
        sets.append({"temperatures": (low, high), **values})
    if sets:
        found[f"heat_capacity_shomate_equation_{phase}"] = sets


def _vaporization(doc, found: dict) -> None:
    tables = doc.xpath("//table[@aria-label='Enthalpy of vaporization']")
    if not tables:
        return
    table = tables[0]
    values = []
    for row in table.xpath(".//tr[position() > 1]"):
        value, temperature = row.xpath("string(td[1])"), row.xpath("string(td[2])")
        if value.strip() and temperature.strip() and "-" not in temperature:
            try:
                values.append((to_float(value), to_float(temperature)))
            except ValueError:
                continue
    if values:
        found["enthalpy_vaporization_values"] = sorted(values, key=lambda pair: pair[1])
        units = [table.xpath(f"string(.//tr[1]/th[{i}])") for i in (1, 2)]
        found["enthalpy_vaporization_units"] = tuple(
            u[u.find("(") + 1 : u.find(")")] if "(" in u else u.strip() for u in units
        )


def _antoine(doc, found: dict) -> None:
    tables = doc.xpath("//table[contains(@aria-label, 'Antoine Equation Parameters')]")
    if not tables:
        return
    sets = []
    for row in tables[0].xpath(".//tr[position() > 1]"):
        try:
            low, high = row.xpath("string(td[1])").split(" to ")
            sets.append(
                {
                    "temperatures": (float(low), float(high)),
                    **{k: float(row.xpath(f"string(td[{i}])")) for i, k in ((2, "A"), (3, "B"))},
                    "C": float(row.xpath("string(td[4])")),
                }
            )
        except ValueError:
            continue
    if sets:
        found["antoine_equation"] = sets


def compound_url(identifier: str) -> str:
    """The WebBook page of a CAS number (``ID=C...``) or, otherwise, a name."""
    identifier = identifier.strip()
    if CAS_RE.match(identifier):
        return f"{WEBBOOK_URL}?ID=C{identifier.replace('-', '')}&Units=SI"
    return f"{WEBBOOK_URL}?Name={quote_plus(identifier)}&Units=SI"


def parse_pages(compound_page: str, url: str, data_pages: dict[str, str]):
    """:class:`NISTThermodynamicProperties` from the compound page and the data pages
    (``{"gas": html, "condensed": html, "phase": html}``, any subset); None without a compound."""
    found, _ = parse_compound_page(compound_page, url)
    if not found:
        return None
    for kind, phase in (("gas", "gas"), ("condensed", "liquid"), ("phase", "")):
        if kind in data_pages:
            parse_data_page(data_pages[kind], phase, found)
    return NISTThermodynamicProperties(**found)


def retrieve(identifier: str, *, client: HttpClient | None = None):
    """The WebBook data of a CAS number or compound name; None if the WebBook has no page.

    Raises :class:`~chemeascode.integrations.http.HttpError` when the WebBook cannot be reached.
    """
    client = client or HttpClient()
    url = compound_url(identifier)
    page = client.get(url, timeout_s=30.0, raise_for_status=False)
    if page.status == 404:
        return None
    if page.status >= 400:
        raise HttpError(f"GET {url}: HTTP {page.status}", url=url, status=page.status)
    found, links = parse_compound_page(page.text, page.url or url)
    if not found:
        return None
    data_pages = {kind: client.get(link).text for kind, link in links.items()}
    return parse_pages(page.text, page.url or url, data_pages)
