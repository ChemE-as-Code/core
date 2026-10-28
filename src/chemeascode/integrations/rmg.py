"""Client of an RMG (Reaction Mechanism Generator) kinetics service: Arrhenius parameters of
gas-phase reactions from RMG's rate rules and kinetics libraries.

RMG-Py does not run in-process (it is conda-only and pinned to an old Python), so it is reached
over HTTP: ``GET <endpoint>?reactants=<SMILES>&reactants=...&products=...`` answering
``{"matches": [...]}``. The caller passes the endpoint; nothing here has a default service
address. A service reloads the RMG database for every request, so one query typically takes
1-3 minutes: the default timeout is 620 s and the default client makes a single attempt (a
caller's own :class:`~chemeascode.integrations.http.HttpClient` applies its own retry policy).

Rate expression: k = A T^n exp(-Ea/RT) (Chemkin, T_ref = 1 K, :data:`RMG_T_REF`); A in SI
units (``A_units``), Ea in J/mol, temperatures in K, pressures in bar.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from chemeascode.integrations.http import HttpClient, HttpError
from chemeascode.integrations.nist_kinetics import in_temperature_range

#: Reference temperature (K) of the Chemkin rate expression k = A T^n exp(-Ea/RT).
RMG_T_REF = 1.0
#: More than a service's own job timeout (600 s).
DEFAULT_TIMEOUT_S = 620.0


@dataclass(frozen=True)
class RmgKineticsRow:
    """One match of the RMG service, in SI units (A in ``A_units`` at ``T_ref`` = 1 K)."""

    reaction: str
    reactants: list[str]  # distinct SMILES
    products: list[str]  # distinct SMILES
    reactant_stoichiometry: dict[str, int] = field(default_factory=dict)
    product_stoichiometry: dict[str, int] = field(default_factory=dict)
    family: str | None = None
    A: float | None = None  # A_units
    A_units: str | None = None
    T_ref: float = RMG_T_REF  # K
    n: float | None = None
    Ea: float | None = None  # J/mol
    T_min: float | None = None  # K
    T_max: float | None = None  # K
    order: float | None = None
    P_range: tuple[float | None, float | None] | None = None  # bar
    kinetics_type: str | None = None
    data_type: str | None = None
    source_library: str | None = None
    reference: str | None = None
    family_exact_match: bool | None = None


def parse_match(match: dict[str, Any]) -> RmgKineticsRow:
    """One entry of the service's ``matches`` list as :class:`RmgKineticsRow`."""
    return RmgKineticsRow(
        reaction=match.get("reaction"),
        reactants=list(match.get("reactants") or []),
        products=list(match.get("products") or []),
        reactant_stoichiometry=dict(match.get("reactant_stoichiometry") or {}),
        product_stoichiometry=dict(match.get("product_stoichiometry") or {}),
        family=match.get("family"),
        A=match.get("A"),
        A_units=match.get("A_units"),
        n=match.get("n"),
        Ea=match.get("Ea"),
        T_min=match.get("Tmin"),
        T_max=match.get("Tmax"),
        order=match.get("order"),
        P_range=(match.get("Pmin"), match.get("Pmax")),
        kinetics_type=match.get("kinetics_type"),
        data_type=match.get("data_type"),
        source_library=match.get("source_library"),
        reference=match.get("reference"),
        family_exact_match=match.get("family_exact_match"),
    )


def query_url(endpoint: str, reactant_smiles: list[str], product_smiles: list[str]) -> str:
    """*endpoint* with one ``reactants``/``products`` query parameter per SMILES."""
    query = urllib.parse.urlencode(
        {"reactants": list(reactant_smiles), "products": list(product_smiles)}, doseq=True
    )
    return f"{endpoint}{'&' if '?' in endpoint else '?'}{query}" if query else endpoint


def query_rmg_kinetics(
    reactant_smiles: list[str],
    product_smiles: list[str] | None = None,
    T_min_query: float | None = None,
    T_max_query: float | None = None,
    *,
    endpoint: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: HttpClient | None = None,
) -> list[RmgKineticsRow]:
    """The RMG records of the reactions generated from *reactant_smiles*.

    *endpoint* is the full URL of the service's query route (e.g.
    ``http://localhost:8001/kinetics/query``). Only forward reactions match: the reactant set
    must equal *reactant_smiles* (order-independent) and, if given, the product set
    *product_smiles*. With *T_min_query* / *T_max_query* (K), only records whose temperature
    range covers them.

    Raises ``ConnectionError`` when the service cannot be reached, and
    :class:`~chemeascode.integrations.http.HttpError` when it answers an error status (with the
    service's ``detail`` in the message when it gives one).
    """
    if not endpoint:
        raise ValueError("endpoint must be the URL of the RMG service's query route")
    client = client or HttpClient(attempts=1)
    url = query_url(endpoint, reactant_smiles, product_smiles or [])
    try:
        response = client.get(url, timeout_s=timeout_s, raise_for_status=False)
    except HttpError as failure:
        raise ConnectionError(
            f"Could not reach the RMG kinetics service at {endpoint}. Is it running?"
        ) from failure
    if response.status >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        message = f"{response.status} error from RMG kinetics service"
        raise HttpError(
            f"{message}: {detail}" if detail else f"{message} ({url})",
            url=url,
            status=response.status,
        )
    data = response.json()
    rows = [parse_match(match) for match in (data or {}).get("matches", [])]
    return [
        row for row in rows if in_temperature_range(row.T_min, row.T_max, T_min_query, T_max_query)
    ]
