"""The NIST kinetics adapter, ported from LLM4ChemE tests/tools/test_nist_kinetics.py. Every
request goes to a fake transport serving saved HTML; the live tests run only with
CHEME_NETWORK_TESTS=1."""

from __future__ import annotations

import math
import os
import urllib.parse

import pytest

from chemeascode.integrations.http import HttpClient, HttpError, Request, Response
from chemeascode.integrations.nist_kinetics import (
    MAX_COMPOUNDS_PER_SIDE,
    NIST_KINETICS_SEARCH_URL,
    NIST_WEBBOOK_URL,
    cas_in_order,
    cas_lookup,
    in_temperature_range,
    nist_scraper,
    parse_cas_number,
    parse_results,
    safe_get_cast,
    si_A,
    si_A_units,
    temp_splitter,
)

network = pytest.mark.skipif(
    os.environ.get("CHEME_NETWORK_TESTS") != "1", reason="set CHEME_NETWORK_TESTS=1"
)

WEBBOOK_PAGE = """<html><body><h1 id="Top">{name}</h1><ul>
<li><strong>Formula:</strong> X</li>
<li><strong>CAS Registry Number:</strong> {cas}</li>
</ul></body></html>"""
WEBBOOK_NOT_FOUND = "<html><body><h1>Name Not Found</h1></body></html>"

# Trimmed from the kinetics.nist.gov ReactionSearch results for CH4 + OH -> CH3 + H2O (the
# first "Review" row, 2021BUR/MAN023102), plus an invented "Experiment" row with one
# temperature and no n.
CH4_OH_RESULTS_HTML = """
<div align="center"><font size="+3"><b>CH4 + &middot;OH &rarr; &middot;CH3 + H2O</b>
</font></div><br>
<b>Rate expression:&nbsp; k(T) = A (T/298 K)<sup>n</sup> e<sup>-Ea/RT</sup></b><br>
<b>Rate expression units:</b><br>
First order:&nbsp; s<sup>-1</sup><br>
Second order:&nbsp; cm<SUP>3</SUP>/molecule s<br>
<form name="KineticsResults" method="post" action="/kinetics/Plot.jsp">
<table border=0><tr><td><input type=submit value=" Create Plot "></td></tr></table>
<table border=0 cellpadding=0 cellspacing=0 width="95%">
<tr>
<th align=left>Plot</th><th width=10>&nbsp;</th>
<th align=left>Squib</th><th width=10>&nbsp;</th>
<th align=left>Temp [K]</th><th width=10>&nbsp;</th>
<th align=left>A</th><th width=10>&nbsp;</th>
<th align=left>n</th><th width=10>&nbsp;</th>
<th align=left>Ea [J/mole]</th><th width=10>&nbsp;</th>
<th align=left>k(298.00 K)</th><th width=10>&nbsp;</th>
<th align=left>Order</th>
</tr>
<tr bgcolor="#ffffff"><td colspan=7><font color="#0000ff" size="+1"><b>Review</b>
</font></td></tr>
<tr bgcolor="#e8e8e8">
<td><input type="checkbox" name="item1" value="item1"></td>
<td width=10>&nbsp;</td>
<td><a onMouseover="showRef('Burgess Jr, D.R.; Manion, J.A. (2021).',event);"
 href="/kinetics/Detail?id=2021BUR/MAN023102:9">2021BUR/MAN023102</a></td>
<td width=10>&nbsp;</td>
<td>200 - 2025</td>
<td width=10>&nbsp;</td>
<td>3.38E-13</td>
<td width=10>&nbsp;</td>
<td>2.23</td>
<td width=10>&nbsp;</td>
<td>9840</td>
<td width=10>&nbsp;</td>
<td>6.38E-15</td><td width=10>&nbsp;</td>
<td>2</td>
</tr>
<tr bgcolor="#ffffff"><td colspan=7><font color="#0000ff" size="+1"><b>Experiment</b>
</font></td></tr>
<tr bgcolor="#e8e8e8">
<td><input type="checkbox" name="item2" value="item2"></td>
<td width=10>&nbsp;</td>
<td><a onMouseover="showRef('Doe, J. (1999).',event);"
 href="/kinetics/Detail?id=1999DOE:1">1999DOE</a></td>
<td width=10>&nbsp;</td>
<td>298</td>
<td width=10>&nbsp;</td>
<td>6.4E-15</td>
<td width=10>&nbsp;</td>
<td></td>
<td width=10>&nbsp;</td>
<td>0</td>
<td width=10>&nbsp;</td>
<td></td><td width=10>&nbsp;</td>
<td>2</td>
</tr>
</table>
</form>
"""
NO_RECORDS_HTML = """<font size="+3"><b>CH4 &rarr; C</b></font>
<form><table><tr><td>Create Plot</td></tr></table></form>"""
NOT_FOUND_HTML = "<html><body><p>No reactions found.</p></body></html>"

# SMILES -> (name, CAS) of the WebBook fake.
COMPOUNDS = {
    "C": ("Methane", "74-82-8"),
    "[OH]": ("Hydroxyl radical", "3352-57-6"),
    "[CH3]": ("Methyl radical", "2229-07-4"),
    "O": ("Water", "7732-18-5"),
    "CCO": ("Ethanol", "64-17-5"),
}

R_NIST = 8.314472  # J/(mol K), as NIST states it
CM3_PER_MOLECULE_TO_M3_PER_MOL = 1e-6 * 6.022e23


class FakeNist:
    """Transport serving the WebBook (by InChI) and one ReactionSearch page."""

    def __init__(self, results_page: str = CH4_OH_RESULTS_HTML, status: int = 200) -> None:
        pytest.importorskip("rdkit")
        from chemeascode.integrations.rdkit import smiles_to_inchi

        self.by_inchi = {smiles_to_inchi(s): entry for s, entry in COMPOUNDS.items()}
        self.results_page = results_page
        self.status = status
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        base, _, query = request.url.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        if base == NIST_WEBBOOK_URL:
            entry = self.by_inchi.get(params.get("InChI"))
            page = WEBBOOK_PAGE.format(name=entry[0], cas=entry[1]) if entry else WEBBOOK_NOT_FOUND
            return Response(200, page, request.url)
        if base == NIST_KINETICS_SEARCH_URL:
            return Response(self.status, self.results_page, request.url)
        raise AssertionError(f"unexpected request {request.url}")

    def search_params(self) -> dict[str, str]:
        search = [r for r in self.requests if r.url.startswith(NIST_KINETICS_SEARCH_URL)]
        assert len(search) == 1
        return dict(urllib.parse.parse_qsl(search[0].url.partition("?")[2]))


def client_for(transport) -> HttpClient:
    return HttpClient(transport=transport, sleep=lambda _: None)


class TestCasLookup:
    def test_known_compound(self):
        fake = FakeNist()
        assert cas_lookup("CCO", client=client_for(fake)) == "64-17-5"
        params = dict(urllib.parse.parse_qsl(fake.requests[0].url.partition("?")[2]))
        assert params == {"InChI": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3", "Units": "SI"}

    def test_unknown_compound_raises(self):
        with pytest.raises(ValueError, match="Could not find CAS Number for 'CCCCCCCCCC'"):
            cas_lookup("CCCCCCCCCC", client=client_for(FakeNist()))

    def test_invalid_smiles_raises_value_error(self):
        pytest.importorskip("rdkit")
        with pytest.raises(ValueError, match="Invalid SMILES"):
            cas_lookup("not_a_smiles(", client=client_for(FakeNist()))

    def test_http_error_propagates(self):
        def failing(request: Request) -> Response:
            return Response(400, "syntax error in the query", request.url)

        pytest.importorskip("rdkit")
        with pytest.raises(HttpError):
            cas_lookup("CCO", client=client_for(failing))

    def test_parse_cas_number(self):
        assert parse_cas_number(WEBBOOK_PAGE.format(name="x", cas=" 64-17-5 ")) == "64-17-5"
        assert parse_cas_number(WEBBOOK_NOT_FOUND) is None
        assert parse_cas_number("<strong>CAS Registry Number:</strong><a>x</a>") is None
        assert parse_cas_number("") is None


class TestCasInOrder:
    def test_single_compound_padded_to_max(self):
        result = cas_in_order(["CCO"], client=client_for(FakeNist()))
        assert result == [64175, 0, 0, 0, 0]
        assert len(result) == MAX_COMPOUNDS_PER_SIDE

    def test_multiple_compounds_sorted_ascending(self):
        assert cas_in_order(["O", "CCO"], client=client_for(FakeNist())) == [
            64175,
            7732185,
            0,
            0,
            0,
        ]

    def test_empty_side_is_all_zero(self):
        assert cas_in_order([], client=client_for(FakeNist())) == [0] * 5

    def test_too_many_compounds_raises(self):
        with pytest.raises(ValueError, match="Too many compounds"):
            cas_in_order(["C"] * (MAX_COMPOUNDS_PER_SIDE + 1), client=client_for(FakeNist()))


class TestSafeGetCast:
    def test_valid_index_with_cast(self):
        assert safe_get_cast(["1", "2"], 0, int) == 1

    def test_valid_index_without_cast(self):
        assert safe_get_cast(["a", "b"], 1) == "b"

    def test_out_of_range_index_returns_none(self):
        assert safe_get_cast(["1"], 5, int) is None

    def test_uncastable_value_returns_none(self):
        assert safe_get_cast(["abc"], 0, float) is None

    def test_none_value_in_list_returns_none(self):
        assert safe_get_cast([None], 0, float) is None
        assert safe_get_cast([None], 0, str) is None  # not the string "None"


class TestTempSplitter:
    def test_none_input(self):
        assert temp_splitter(None) == (None, None)

    def test_single_temperature(self):
        assert temp_splitter("298") == (298.0, 298.0)

    def test_temperature_range(self):
        assert temp_splitter("200-400") == (200.0, 400.0)
        assert temp_splitter("200 - 2025") == (200.0, 2025.0)

    def test_unparseable_range_returns_none(self):
        assert temp_splitter("abc-def") == (None, None)

    def test_unparseable_single_returns_none(self):
        assert temp_splitter("not_a_number") == (None, None)


class TestSiA:
    def test_missing_A_returns_none(self):
        assert si_A(None, 1) is None

    def test_missing_order_returns_none(self):
        assert si_A(1e13, None) is None

    def test_order_1_is_unchanged(self):
        assert si_A(1e13, 1) == 1e13

    def test_order_0_conversion(self):
        assert si_A(1e13, 0) == pytest.approx(1.6605778811026237e-05)

    def test_order_2_conversion(self):
        assert si_A(1e13, 2) == pytest.approx(6.022000000000001e30)

    def test_order_3_conversion(self):
        assert si_A(1e13, 3) == pytest.approx(3.6264484000000004e48)

    def test_unsupported_order_returns_none(self):
        assert si_A(1e13, 4) is None


class TestSiAUnits:
    @pytest.mark.parametrize(
        ("order", "units"),
        [(0, "mol/(m^3*s)"), (1.0, "s^-1"), (2.0, "m^3/(mol*s)"), (3, "m^6/(mol^2*s)")],
    )
    def test_supported_orders(self, order, units):
        assert si_A_units(order) == units

    def test_unsupported_or_missing_order_returns_none(self):
        assert si_A_units(4) is None
        assert si_A_units(None) is None


class TestParseResults:
    def rows(self):
        reaction, rows = parse_results(CH4_OH_RESULTS_HTML, ["C", "[OH]"], ["[CH3]", "O"])
        assert reaction == "CH4 + ·OH → ·CH3 + H2O"
        assert len(rows) == 2
        return rows

    def test_A_converted_to_si_and_tagged_with_nist_T_ref(self):
        row = self.rows()[0]
        assert pytest.approx(3.38e-13 * CM3_PER_MOLECULE_TO_M3_PER_MOL) == row.A
        assert row.A_units == "m^3/(mol*s)"
        assert row.T_ref == 298.0
        assert row.n == 2.23
        assert row.Ea == 9840.0
        assert row.order == 2.0
        assert (row.T_min, row.T_max) == (200.0, 2025.0)

    def test_k_298K_in_same_si_units_as_A(self):
        row = self.rows()[0]
        assert row.k_298K == pytest.approx(6.38e-15 * CM3_PER_MOLECULE_TO_M3_PER_MOL)
        # k(298 K) = A exp(-Ea/(R 298 K)) with NIST's T_ref = 298 K: same units for both.
        assert row.k_298K == pytest.approx(row.A * math.exp(-row.Ea / (R_NIST * 298.0)), rel=1e-2)

    def test_reference_squib_and_data_type(self):
        review, experiment = self.rows()
        assert review.reference == "Burgess Jr, D.R.; Manion, J.A. (2021)."
        assert review.squib == "2021BUR/MAN023102"
        assert review.data_type == "Review"
        assert experiment.data_type == "Experiment"
        assert experiment.reactants == ["C", "[OH]"]
        assert experiment.products == ["[CH3]", "O"]

    def test_empty_cells_are_missing(self):
        experiment = self.rows()[1]
        assert experiment.n is None
        assert experiment.k_298K is None
        assert experiment.Ea == 0.0
        assert (experiment.T_min, experiment.T_max) == (298.0, 298.0)

    def test_no_results_table_gives_no_rows(self):
        assert parse_results(NO_RECORDS_HTML, ["C"], []) == ("CH4 → C", [])

    def test_no_reaction_string_raises(self):
        with pytest.raises(ValueError, match="did not return a reaction string"):
            parse_results(NOT_FOUND_HTML, ["C"], [])
        with pytest.raises(ValueError, match="did not return a reaction string"):
            parse_results("", ["C"], [])


class TestNistScraper:
    def test_search_url_and_records(self):
        fake = FakeNist()
        records = nist_scraper(["C", "[OH]"], ["[CH3]", "O"], client=client_for(fake))
        assert [record.squib for record in records] == ["2021BUR/MAN023102", "1999DOE"]
        assert fake.search_params() == {
            "r0": "74828",
            "r1": "3352576",
            "r2": "0",
            "r3": "0",
            "r4": "0",
            "p0": "2229074",
            "p1": "7732185",
            "p2": "0",
            "p3": "0",
            "p4": "0",
            "expandResults": "true",
        }

    def test_temperature_filtering(self):
        def squibs(T_min=None, T_max=None):
            client = client_for(FakeNist())
            records = nist_scraper(["C", "[OH]"], ["[CH3]", "O"], T_min, T_max, client=client)
            return [record.squib for record in records]

        assert squibs(250, 350) == ["2021BUR/MAN023102"]
        assert squibs(298, 298) == ["2021BUR/MAN023102", "1999DOE"]
        assert squibs(100, None) == []
        assert squibs(None, 3000) == []

    def test_reaction_not_found_raises(self):
        fake = FakeNist(results_page=NOT_FOUND_HTML)
        with pytest.raises(ValueError, match="did not return a reaction string"):
            nist_scraper(["CCO"], ["C"], client=client_for(fake))

    def test_unknown_compound_raises_before_the_search(self):
        fake = FakeNist()
        with pytest.raises(ValueError, match="Could not find CAS Number"):
            nist_scraper(["CCCCCCCCCC"], [], client=client_for(fake))
        assert not any(r.url.startswith(NIST_KINETICS_SEARCH_URL) for r in fake.requests)

    def test_server_error_raises_http_error(self):
        with pytest.raises(HttpError):
            nist_scraper(["C"], [], client=client_for(FakeNist(status=500)))


def test_in_temperature_range():
    assert in_temperature_range(200.0, 400.0, 250.0, 350.0)
    assert not in_temperature_range(300.0, 400.0, 200.0, 500.0)
    assert in_temperature_range(None, None, 200.0, 500.0)
    assert in_temperature_range(300.0, 400.0, None, None)


def test_a_one_sided_temperature_query_must_lie_in_the_record_range():
    """pre-release issue 197: --tmin alone kept a record valid only below it (and --tmax alone one
    only above it)."""
    assert not in_temperature_range(200.0, 400.0, 600.0, None)
    assert not in_temperature_range(1000.0, 2000.0, None, 300.0)
    assert in_temperature_range(200.0, 800.0, 600.0, None)
    assert in_temperature_range(200.0, 800.0, None, 300.0)
    assert not in_temperature_range(None, 400.0, 600.0, None)
    assert in_temperature_range(None, None, 600.0, None)
    assert not in_temperature_range(200.0, 400.0, 600.0, 700.0)


@network
class TestLive:
    def test_cas_lookup(self):
        pytest.importorskip("rdkit")
        assert cas_lookup("CCO") == "64-17-5"
        assert cas_lookup("O") == "7732-18-5"

    def test_n2o5_decomposition(self):
        pytest.importorskip("rdkit")
        reactants = ["[O-][N+](=O)O[N+](=O)[O-]"]
        products = ["[O-][N+]=O", "[O]N(=O)=O"]
        records = nist_scraper(reactants, products)
        assert records
        assert all(30_000 < r.Ea < 300_000 for r in records if r.Ea is not None)
