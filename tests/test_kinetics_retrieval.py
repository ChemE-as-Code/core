"""retrieve_kinetics, ported from LLM4ChemE tests/tools/test_kinetics_retriever.py: RMG and NIST
are fake transports (the adapters are tested in test_nist_kinetics.py / test_rmg_client.py)."""

from __future__ import annotations

import json
import threading

import pytest

from chemeascode.domains.chemistry.kinetics.records import NISTKineticsRecord, RMGKineticsRecord
from chemeascode.domains.chemistry.kinetics.retrieval import (
    retrieve_kinetics,
    retrieve_kinetics_nist,
    retrieve_kinetics_rmg,
)
from chemeascode.integrations.http import HttpClient, Request, Response
from chemeascode.integrations.nist_kinetics import NIST_KINETICS_SEARCH_URL, NIST_WEBBOOK_URL

from .test_nist_kinetics import CH4_OH_RESULTS_HTML, FakeNist
from .test_rmg_client import SAMPLE_MATCH

pytest.importorskip("rdkit")

ENDPOINT = "http://rmg.test/kinetics/query"
R, P = ["C", "[OH]"], ["[CH3]", "O"]


class FakeBoth:
    """RMG at ENDPOINT, NIST (WebBook + ReactionSearch) through FakeNist."""

    def __init__(self, rmg_status=200, nist_page=CH4_OH_RESULTS_HTML, barrier=None) -> None:
        self.nist = FakeNist(results_page=nist_page)
        self.rmg_status = rmg_status
        self.barrier = barrier
        self.urls: list[str] = []
        self.lock = threading.Lock()

    def __call__(self, request: Request) -> Response:
        with self.lock:
            self.urls.append(request.url)
        if request.url.startswith(ENDPOINT):
            if self.barrier:
                self.barrier.wait()
            body = {"matches": [SAMPLE_MATCH]} if self.rmg_status == 200 else {"detail": "down"}
            return Response(self.rmg_status, json.dumps(body), request.url)
        if self.barrier and request.url.startswith(NIST_KINETICS_SEARCH_URL):
            self.barrier.wait()
        with self.lock:
            return self.nist(request)


def client(fake) -> HttpClient:
    return HttpClient(transport=fake, attempts=1, sleep=lambda _: None)


def test_combines_both_sources():
    result = retrieve_kinetics(R, P, rmg_endpoint=ENDPOINT, client=client(FakeBoth()))
    assert [r.family for r in result.rmg_records] == ["H_Abstraction"]
    assert all(isinstance(r, RMGKineticsRecord) for r in result.rmg_records)
    assert [r.squib for r in result.nist_records] == ["2021BUR/MAN023102", "1999DOE"]
    assert all(isinstance(r, NISTKineticsRecord) for r in result.nist_records)
    assert result.errors == {} and result.skipped == {}


def test_without_endpoint_only_nist_is_queried():
    fake = FakeBoth()
    result = retrieve_kinetics(R, P, client=client(fake))
    assert result.rmg_records == []
    assert len(result.nist_records) == 2
    assert result.skipped == {"rmg": "no RMG endpoint given"}
    assert not any(url.startswith(ENDPOINT) for url in fake.urls)


def test_runs_both_sources_concurrently():
    """Both requests wait for each other: sequential calls would break the barrier."""
    fake = FakeBoth(barrier=threading.Barrier(2, timeout=10))
    result = retrieve_kinetics(R, P, rmg_endpoint=ENDPOINT, client=client(fake))
    assert result.errors == {}


def test_rmg_failure_does_not_prevent_nist_results():
    fake = FakeBoth(rmg_status=500)
    result = retrieve_kinetics(R, P, rmg_endpoint=ENDPOINT, client=client(fake))
    assert result.rmg_records == []
    assert len(result.nist_records) == 2
    assert result.errors["rmg"].startswith("HttpError: 500 error from RMG kinetics service")


def test_nist_failure_does_not_prevent_rmg_results():
    fake = FakeBoth(nist_page="<p>nothing</p>")
    result = retrieve_kinetics(R, P, rmg_endpoint=ENDPOINT, client=client(fake))
    assert len(result.rmg_records) == 1
    assert result.nist_records == []
    assert "ValueError" in result.errors["nist"]


def test_both_fail_returns_empty_with_both_errors():
    fake = FakeBoth(rmg_status=500, nist_page="")
    result = retrieve_kinetics(R, P, rmg_endpoint=ENDPOINT, client=client(fake))
    assert result.rmg_records == [] and result.nist_records == []
    assert set(result.errors) == {"rmg", "nist"}


def test_temperature_range_is_passed_to_both():
    fake = FakeBoth()
    result = retrieve_kinetics(R, P, 250, 350, rmg_endpoint=ENDPOINT, client=client(fake))
    assert [r.squib for r in result.nist_records] == ["2021BUR/MAN023102"]
    assert len(result.rmg_records) == 1  # no temperature range: always included


def test_nist_without_products_queries_empty_product_slots():
    fake = FakeBoth()
    records = retrieve_kinetics_nist(R, client=client(fake))
    assert all(r.products == [] for r in records)
    assert all(r.T_ref == 298.0 for r in records)
    search = [u for u in fake.urls if u.startswith(NIST_KINETICS_SEARCH_URL)]
    assert "p0=0&p1=0&p2=0&p3=0&p4=0" in search[0]
    assert sum(u.startswith(NIST_WEBBOOK_URL) for u in fake.urls) == 2


def test_rmg_records_are_models_at_1_K():
    records = retrieve_kinetics_rmg(R, P, endpoint=ENDPOINT, client=client(FakeBoth()))
    assert records[0].T_ref == 1.0
    assert records[0].Ea == 31505.52
