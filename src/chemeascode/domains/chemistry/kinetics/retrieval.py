"""Retrieve the kinetics records of a reaction from RMG and NIST.

:func:`retrieve_kinetics` queries both sources (in two threads, since an RMG query takes
minutes) and reports each source's failure separately, so one failing source does not lose the
other's records. RMG is queried only when the caller gives the service's endpoint; otherwise
the result lists it under ``skipped``. Every request goes through the adapters'
:class:`~chemeascode.integrations.http.HttpClient`, so tests pass a fake transport.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from chemeascode.integrations import nist_kinetics, rmg
from chemeascode.integrations.http import HttpClient

from .records import NISTKineticsRecord, RMGKineticsRecord


class KineticsRetrieval(BaseModel):
    """The records of each source, and why a source gave none."""

    rmg_records: list[RMGKineticsRecord] = Field(default_factory=list)
    nist_records: list[NISTKineticsRecord] = Field(default_factory=list)
    errors: dict[str, str] = Field(
        default_factory=dict, description="Source ('rmg', 'nist') -> 'ErrorType: message'"
    )
    skipped: dict[str, str] = Field(
        default_factory=dict, description="Source not queried -> the reason"
    )


def retrieve_kinetics_rmg(
    reactant_smiles: list[str],
    product_smiles: list[str] | None = None,
    T_min: float | None = None,
    T_max: float | None = None,
    *,
    endpoint: str,
    client: HttpClient | None = None,
) -> list[RMGKineticsRecord]:
    """The RMG records of the reaction (see
    :func:`chemeascode.integrations.rmg.query_rmg_kinetics`); A at T_ref = 1 K."""
    rows = rmg.query_rmg_kinetics(
        reactant_smiles, product_smiles, T_min, T_max, endpoint=endpoint, client=client
    )
    return [RMGKineticsRecord.from_row(row) for row in rows]


def retrieve_kinetics_nist(
    reactant_smiles: list[str],
    product_smiles: list[str] | None = None,
    T_min: float | None = None,
    T_max: float | None = None,
    *,
    client: HttpClient | None = None,
) -> list[NISTKineticsRecord]:
    """The NIST records of the reaction (see
    :func:`chemeascode.integrations.nist_kinetics.nist_scraper`); A at T_ref = 298 K."""
    rows = nist_kinetics.nist_scraper(
        reactant_smiles, product_smiles or [], T_min, T_max, client=client
    )
    return [NISTKineticsRecord.from_row(row) for row in rows]


def _outcome(future) -> tuple[list, str | None]:
    try:
        return future.result(), None
    except Exception as failure:  # noqa: BLE001 - each source's failure is reported, not raised
        return [], f"{type(failure).__name__}: {failure}"


def retrieve_kinetics(
    reactant_smiles: list[str],
    product_smiles: list[str] | None = None,
    T_min: float | None = None,
    T_max: float | None = None,
    *,
    rmg_endpoint: str | None = None,
    client: HttpClient | None = None,
) -> KineticsRetrieval:
    """The RMG and NIST records of the reaction *reactant_smiles* (-> *product_smiles*),
    optionally only those covering *T_min* to *T_max* (K).

    *rmg_endpoint* is the URL of the RMG service's query route; without it only NIST is
    queried and ``skipped["rmg"]`` says so. *client* is used for every request (the adapters'
    defaults otherwise; RMG's makes a single attempt). A source that fails gives no records
    and an entry in ``errors``.
    """
    result = KineticsRetrieval()
    with ThreadPoolExecutor(max_workers=2) as executor:
        rmg_future = (
            executor.submit(
                retrieve_kinetics_rmg,
                reactant_smiles,
                product_smiles,
                T_min,
                T_max,
                endpoint=rmg_endpoint,
                client=client,
            )
            if rmg_endpoint
            else None
        )
        nist_future = executor.submit(
            retrieve_kinetics_nist, reactant_smiles, product_smiles, T_min, T_max, client=client
        )
        if rmg_future is None:
            result.skipped["rmg"] = "no RMG endpoint given"
        else:
            result.rmg_records, error = _outcome(rmg_future)
            if error:
                result.errors["rmg"] = error
        result.nist_records, error = _outcome(nist_future)
        if error:
            result.errors["nist"] = error
    return result
