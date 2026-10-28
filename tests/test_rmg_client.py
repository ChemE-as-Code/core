"""The RMG service client, ported from LLM4ChemE tests/tools/test_rmg_kinetics.py; the service
is a fake transport."""

from __future__ import annotations

import json
import urllib.parse

import pytest

from chemeascode.integrations.http import HttpClient, HttpError, Request, Response
from chemeascode.integrations.rmg import DEFAULT_TIMEOUT_S, query_rmg_kinetics, query_url

ENDPOINT = "http://rmg.test/kinetics/query"
SAMPLE_MATCH = {
    "reaction": "spc1(2) + spc0(1) <=> [H][H](7) + C[CH2](6)",
    "reactants": ["[H]", "CC"],
    "products": ["[H][H]", "[CH2]C"],
    "A": 115.0,
    "A_units": "m^3/(mol*s)",
    "n": 1.9,
    "Ea": 31505.52,
    "Tmin": None,
    "Tmax": None,
    "order": 2,
    "Pmin": None,
    "Pmax": None,
    "family": "H_Abstraction",
    "source_library": "H_Abstraction/training",
    "data_type": "training",
    "kinetics_type": "Arrhenius",
    "reference": "Matched reaction 210 C2H6 + H <=> C2H5b + H2_p in H_Abstraction/training",
    "family_exact_match": True,
}


class FakeService:
    def __init__(self, payload=None, status: int = 200, fail: bool = False) -> None:
        self.payload = {"matches": [SAMPLE_MATCH]} if payload is None else payload
        self.status, self.fail = status, fail
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        if self.fail:
            raise HttpError("connection refused", url=request.url)
        return Response(self.status, json.dumps(self.payload), request.url)

    def query(self) -> list[tuple[str, str]]:
        return urllib.parse.parse_qsl(self.requests[-1].url.partition("?")[2])


def query(fake: FakeService, *args, **kwargs):
    client = HttpClient(transport=fake, sleep=lambda _: None)
    return query_rmg_kinetics(*args, endpoint=ENDPOINT, client=client, **kwargs)


class TestQueryRmgKinetics:
    def test_successful_query_returns_records(self):
        records = query(FakeService(), ["CC", "[H]"], ["[H][H]", "C[CH2]"])
        assert len(records) == 1
        record = records[0]
        assert record.family == "H_Abstraction"
        assert (record.A, record.n, record.Ea) == (115.0, 1.9, 31505.52)
        assert record.P_range == (None, None)
        assert record.family_exact_match is True
        assert record.T_ref == 1.0

    def test_query_has_one_parameter_per_smiles(self):
        fake = FakeService()
        query(fake, ["CC", "[H]"], ["[H][H]", "C[CH2]"])
        assert fake.requests[0].url.startswith(ENDPOINT + "?")
        assert fake.query() == [
            ("reactants", "CC"),
            ("reactants", "[H]"),
            ("products", "[H][H]"),
            ("products", "C[CH2]"),
        ]

    def test_none_product_smiles_sends_no_products(self):
        fake = FakeService({"matches": []})
        assert query(fake, ["CC"]) == []
        assert fake.query() == [("reactants", "CC")]

    def test_missing_matches_key_returns_empty_list(self):
        assert query(FakeService({}), ["CC"], ["C"]) == []

    def test_stoichiometry(self):
        match = {**SAMPLE_MATCH, "reactant_stoichiometry": {"[H]": 2}}
        record = query(FakeService({"matches": [match]}), ["[H]"])[0]
        assert record.reactant_stoichiometry == {"[H]": 2}
        assert record.product_stoichiometry == {}

    def test_default_timeout_is_generous(self):
        fake = FakeService({"matches": []})
        query(fake, ["CC"], ["C"])
        assert fake.requests[0].timeout_s == DEFAULT_TIMEOUT_S >= 600

    def test_http_error_propagates_with_detail(self):
        fake = FakeService({"detail": "RMG job timed out"}, status=500)
        with pytest.raises(HttpError, match="500 error from RMG kinetics service: RMG job"):
            query(fake, ["CC"], ["C"])

    def test_http_error_without_detail(self):
        with pytest.raises(HttpError, match="502 error"):
            query(FakeService({}, status=502), ["CC"], ["C"])

    def test_connection_error_raises_clear_message(self):
        with pytest.raises(ConnectionError, match="RMG kinetics service at http://rmg.test"):
            query(FakeService(fail=True), ["CC"], ["C"])

    def test_endpoint_is_required(self):
        with pytest.raises(TypeError):
            query_rmg_kinetics(["CC"])  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="endpoint"):
            query_rmg_kinetics(["CC"], endpoint="")

    def test_temperature_filter_excludes_out_of_range_records(self):
        narrow = {**SAMPLE_MATCH, "Tmin": 300.0, "Tmax": 400.0}
        fake = FakeService({"matches": [narrow]})
        assert query(fake, ["CC", "[H]"], T_min_query=200, T_max_query=500) == []

    def test_temperature_filter_includes_contained_range(self):
        wide = {**SAMPLE_MATCH, "Tmin": 200.0, "Tmax": 500.0}
        fake = FakeService({"matches": [wide]})
        assert len(query(fake, ["CC", "[H]"], T_min_query=300, T_max_query=400)) == 1

    def test_temperature_filter_none_range_always_included(self):
        assert len(query(FakeService(), ["CC", "[H]"], T_min_query=200, T_max_query=500)) == 1


def test_query_url_keeps_an_existing_query_string():
    assert query_url("http://x/q?key=1", ["C"], []) == "http://x/q?key=1&reactants=C"
    assert query_url("http://x/q", [], []) == "http://x/q"
