"""The NIST Chemical Kinetics Database (kinetics.nist.gov) and the CAS lookup through the NIST
Chemistry WebBook (webbook.nist.gov): network access and HTML parsing only.

NIST has no API for the kinetics database, so the ReactionSearch results page is parsed:

1. :func:`cas_in_order` resolves each reactant and product SMILES to a CAS Registry Number
   (:func:`cas_lookup` asks the WebBook by InChI) and sorts them, as the search URL expects
   (up to five reactants and five products, unused slots 0).
2. :func:`nist_scraper` sends the search and parses the results table (:func:`parse_results`)
   into one :class:`NistKineticsRow` per data row.

Conventions of the parsed values (stated in the header of every results page):

- Rate expression: k(T) = A (T/298 K)^n exp(-Ea/RT), so A refers to T_ref = 298 K
  (:data:`NIST_T_REF`; RMG and Chemkin use T_ref = 1 K).
- Units of A and of the k(298.00 K) column (the default unit setting, which the search URL
  does not override): s^-1, cm^3/(molecule s), cm^6/(molecule^2 s) for first, second and third
  order. :func:`si_A` converts both to mol/m^3-based SI units; A stays at T_ref = 298 K.
- Ea in J/mol (column "Ea [J/mole]").

Only the first results page is read. RDKit (for the InChI) is imported inside the functions
through :mod:`chemeascode.integrations.rdkit`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import lxml.html

from chemeascode.integrations.http import HttpClient
from chemeascode.integrations.rdkit import smiles_to_inchi

NIST_WEBBOOK_URL = "https://webbook.nist.gov/cgi/cbook.cgi"
NIST_KINETICS_SEARCH_URL = "https://kinetics.nist.gov/kinetics/ReactionSearch"
MAX_COMPOUNDS_PER_SIDE = 5
#: Reference temperature (K) of the NIST rate expression k = A (T/298 K)^n exp(-Ea/RT).
NIST_T_REF = 298.0

#: molecule/cm^3 -> mol/m^3 (the Avogadro constant as NIST's own pages round it).
_MOLECULE_PER_CM3_TO_MOL_PER_M3 = 1 / 6.022e23 * (100 / 1) ** 3

#: SI units of A and k after :func:`si_A`, by reaction order (the RMG service's unit strings).
SI_A_UNITS_BY_ORDER: dict[float, str] = {
    0: "mol/(m^3*s)",
    1: "s^-1",
    2: "m^3/(mol*s)",
    3: "m^6/(mol^2*s)",
}


@dataclass(frozen=True)
class NistKineticsRow:
    """One data row of a NIST ReactionSearch results page, in SI units.

    ``A`` and ``k_298K`` are in ``A_units`` (mol, m, s); ``A`` refers to ``T_ref`` = 298 K.
    """

    reaction: str  # the reaction as NIST writes it
    reactants: list[str]  # SMILES, as queried
    products: list[str]  # SMILES, as queried
    A: float | None  # A_units, at T_ref
    A_units: str | None
    T_ref: float  # K
    n: float | None  # temperature exponent, dimensionless
    Ea: float | None  # J/mol
    T_min: float | None  # K
    T_max: float | None  # K
    order: float | None
    k_298K: float | None  # A_units
    data_type: str | None  # the section heading: "Experiment", "Review", "Theory", ...
    reference: str | None
    squib: str | None


def cas_lookup(smiles: str, *, client: HttpClient | None = None) -> str:
    """The CAS Registry Number of *smiles* (e.g. "64-17-5" for "CCO") from the NIST WebBook.

    The WebBook takes the full InChI (an InChIKey is rejected with HTTP 400). Raises
    ``ValueError`` for an invalid SMILES or when the WebBook page shows no CAS number, and
    :class:`~chemeascode.integrations.http.HttpError` when the request fails.
    """
    inchi = smiles_to_inchi(smiles)
    client = client or HttpClient()
    response = client.get(NIST_WEBBOOK_URL, {"InChI": inchi, "Units": "SI"}, timeout_s=10.0)
    cas = parse_cas_number(response.text)
    if cas is None:
        raise ValueError(f"Could not find CAS Number for '{smiles}' ({inchi})")
    return cas


def parse_cas_number(page: str) -> str | None:
    """The text after ``<strong>CAS Registry Number:</strong>`` on a WebBook page, or None."""
    if not page.strip():
        return None
    doc = lxml.html.fromstring(page)
    for label in doc.iter("strong"):
        if label.text_content().strip() == "CAS Registry Number:":
            text = (label.tail or "").strip()
            return text or None
    return None


def cas_in_order(compounds: list[str], *, client: HttpClient | None = None) -> list[int]:
    """CAS numbers of *compounds* (SMILES) without dashes, ascending, padded with 0 to
    :data:`MAX_COMPOUNDS_PER_SIDE`: the r0..r4 / p0..p4 slots of the NIST search URL.

    Raises ``ValueError`` for more than :data:`MAX_COMPOUNDS_PER_SIDE` compounds.
    """
    if len(compounds) > MAX_COMPOUNDS_PER_SIDE:
        raise ValueError(
            f"Too many compounds for NIST kinetics search "
            f"(max {MAX_COMPOUNDS_PER_SIDE}, got {len(compounds)})"
        )
    client = client or HttpClient()
    cas_numbers = sorted(int(cas_lookup(c, client=client).replace("-", "")) for c in compounds)
    return cas_numbers + [0] * (MAX_COMPOUNDS_PER_SIDE - len(cas_numbers))


def safe_get_cast(values: list, index: int, cast: Callable[[Any], Any] | None = None) -> Any:
    """``cast(values[index])``, or None when the index is out of range, the value is None or
    the cast fails."""
    try:
        value = values[index]
    except IndexError:
        return None
    if value is None:
        return None
    try:
        return cast(value) if cast is not None else value
    except (ValueError, TypeError):
        return None


def temp_splitter(temp: str | None) -> tuple[float | None, float | None]:
    """``(T_min, T_max)`` in K of a NIST "Temp [K]" cell ("298" or "200 - 400"); a single
    temperature is both. ``(None, None)`` when the cell is missing or does not parse."""
    if temp is None:
        return None, None
    if "-" in temp:
        low, high = temp.split("-", 1)
        try:
            return float(low), float(high)
        except (ValueError, TypeError):
            return None, None
    try:
        value = float(temp)
    except (ValueError, TypeError):
        return None, None
    return value, value


def si_A(A: float | None, order: float | None) -> float | None:
    """A pre-exponential factor (or rate constant) in NIST's molecule/cm^3-based units, in
    mol/m^3-based SI units; None when either is missing or *order* is not 0, 1, 2 or 3. The
    reference temperature is not changed."""
    if A is None or order is None:
        return None
    conversion = _MOLECULE_PER_CM3_TO_MOL_PER_M3
    if order == 0:
        return A * conversion
    if order == 1:
        return A
    if order == 2:
        return A / conversion
    if order == 3:
        return A / conversion**2
    return None


def si_A_units(order: float | None) -> str | None:
    """The SI units :func:`si_A` gives for *order*, or None if it does not support it."""
    if order is None:
        return None
    return SI_A_UNITS_BY_ORDER.get(order)


def _cell_text(cell) -> str | None:
    """The stripped text fragments of *cell* joined without a separator, or None if empty."""
    return "".join(fragment.strip() for fragment in cell.itertext()) or None


def _section_heading(row) -> str | None:
    """The nearest ``<b>`` before *row* in document order: the data type heading."""
    found = row.xpath("(preceding::b | ancestor::b)[last()]")
    return found[0].text_content().strip() if found else None


def _reference(link) -> str | None:
    """The reference in ``onmouseover="showRef('<reference>', event);"``."""
    handler = link.get("onmouseover") or ""
    parts = handler.split("'")
    return parts[1] if len(parts) > 1 else None


def parse_results(
    page: str, reactant_smiles: list[str], product_smiles: list[str]
) -> tuple[str, list[NistKineticsRow]]:
    """The reaction string and the data rows of a ReactionSearch results *page*.

    The rows are those of the second table inside the first ``<form>``; a row without a link
    (a heading or spacer row) is skipped. Raises ``ValueError`` when the page has no reaction
    string (the query matched nothing NIST knows).
    """
    doc = lxml.html.fromstring(page) if page.strip() else None
    title = doc.xpath("//font[@size='+3']") if doc is not None else []
    if not title:
        raise ValueError("NIST did not return a reaction string for this query")
    reaction = title[0].text_content().strip()

    forms = doc.xpath("//form")
    tables = forms[0].xpath(".//table") if forms else []
    if len(tables) < 2:
        return reaction, []
    table = tables[1]
    columns = [th.text_content().replace("\xa0", "").strip() for th in table.iter("th")]

    rows = []
    for row in table.iter("tr"):
        links = row.xpath(".//a[@href]")
        if not links:
            continue
        cells = [_cell_text(td) for td in row.iter("td")]
        kinetics: dict[str, Any] = {}
        for index, name in enumerate(columns):
            cast = str if name in ("Squib", "Temp [K]") else float
            kinetics[name] = safe_get_cast(cells, index, cast)
        T_min, T_max = temp_splitter(kinetics.get("Temp [K]"))
        order = kinetics.get("Order")
        rows.append(
            NistKineticsRow(
                reaction=reaction,
                reactants=list(reactant_smiles),
                products=list(product_smiles),
                A=si_A(kinetics.get("A"), order),
                A_units=si_A_units(order),
                T_ref=NIST_T_REF,
                n=kinetics.get("n"),
                Ea=kinetics.get("Ea [J/mole]"),
                T_min=T_min,
                T_max=T_max,
                order=order,
                k_298K=si_A(kinetics.get("k(298.00 K)"), order),
                data_type=_section_heading(row),
                reference=_reference(links[0]),
                squib=kinetics.get("Squib"),
            )
        )
    return reaction, rows


def in_temperature_range(
    T_min: float | None,
    T_max: float | None,
    T_min_query: float | None,
    T_max_query: float | None,
) -> bool:
    """Whether a record valid from *T_min* to *T_max* (K) covers the queried range; a missing
    bound of the record never excludes it. A one-sided query is the temperature it names: the
    record must cover that bound, not just extend to the same side."""
    if T_min_query is None:
        T_min_query = T_max_query
    if T_max_query is None:
        T_max_query = T_min_query
    return (T_min_query is None or T_min is None or T_min_query >= T_min) and (
        T_max_query is None or T_max is None or T_max_query <= T_max
    )


def nist_scraper(
    reactant_smiles: list[str],
    product_smiles: list[str],
    T_min_query: float | None = None,
    T_max_query: float | None = None,
    *,
    client: HttpClient | None = None,
) -> list[NistKineticsRow]:
    """The NIST kinetics records of the reaction *reactant_smiles* -> *product_smiles*.

    With *T_min_query* / *T_max_query* (K), only records whose temperature range covers them.
    Empty when NIST lists no records. Raises ``ValueError`` when a compound has no CAS number
    or NIST returns no reaction for the query, and
    :class:`~chemeascode.integrations.http.HttpError` when a request fails.
    """
    client = client or HttpClient()
    reactant_cas = cas_in_order(reactant_smiles, client=client)
    product_cas = cas_in_order(product_smiles, client=client)
    params: dict[str, Any] = {f"r{i}": cas for i, cas in enumerate(reactant_cas)}
    params.update({f"p{i}": cas for i, cas in enumerate(product_cas)})
    params["expandResults"] = "true"
    response = client.get(NIST_KINETICS_SEARCH_URL, params, timeout_s=60.0)
    _, rows = parse_results(response.text, reactant_smiles, product_smiles)
    return [
        row for row in rows if in_temperature_range(row.T_min, row.T_max, T_min_query, T_max_query)
    ]
