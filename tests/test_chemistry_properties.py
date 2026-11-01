"""Property retrieval (domains/chemistry/properties.py) and its web adapters, without network:
every adapter gets an HttpClient with a fake transport."""

from __future__ import annotations

import json
import math

import pytest

from chemeascode.domains.chemistry.properties import (
    ANTOINE_FORM,
    SOURCE_ORDER,
    PropertyRetriever,
    Source,
    grappa_antoine_to_canonical,
    relative_volatility,
    retrieve_properties,
)
from chemeascode.integrations import nist_webbook, osha, prediction_services, pubchem, unifac
from chemeascode.integrations.http import HttpClient, HttpError, Response


def fake_client(routes: dict[str, tuple[int, str]], seen: list | None = None) -> HttpClient:
    """Answers the first route whose key is a substring of the URL; 404 otherwise."""

    def transport(request):
        if seen is not None:
            seen.append(request)
        for key, (status, text) in routes.items():
            if key in request.url:
                return Response(status, text, request.url)
        return Response(404, "not found", request.url)

    return HttpClient(transport=transport, sleep=lambda s: None)


# -- http ----------------------------------------------------------------------------------


def test_http_retries_transient_statuses_then_succeeds():
    answers = iter([Response(503, "", "u"), Response(200, "ok", "u")])
    client = HttpClient(transport=lambda r: next(answers), sleep=lambda s: None)
    assert client.get("https://x.test/a", {"q": 1}).text == "ok"


def test_http_raises_on_error_status_with_the_status():
    client = fake_client({})
    with pytest.raises(HttpError) as failure:
        client.get("https://x.test/missing")
    assert failure.value.status == 404
    assert client.get("https://x.test/missing", raise_for_status=False).status == 404


# -- PubChem --------------------------------------------------------------------------------

PROPS = {
    "PropertyTable": {
        "Properties": [
            {
                "CID": 702,
                "MolecularFormula": "C2H6O",
                "MolecularWeight": "46.07",
                "ConnectivitySMILES": "CCO",
                "IUPACName": "ethanol",
            }
        ]
    }
}
SYNONYMS = {"InformationList": {"Information": [{"Synonym": ["ethanol", "64-17-5", "x"]}]}}


def pubchem_client(seen=None):
    return fake_client(
        {
            "/compound/name/cids/JSON": (200, json.dumps({"IdentifierList": {"CID": [702]}})),
            "/property/": (200, json.dumps(PROPS)),
            "/synonyms/": (200, json.dumps(SYNONYMS)),
        },
        seen,
    )


def test_pubchem_search_parses_properties_and_cas():
    seen = []
    [found] = pubchem.search_compounds("ethanol", client=pubchem_client(seen))
    assert (found.cid, found.molecular_weight, found.canonical_smiles) == (702, 46.07, "CCO")
    assert found.cas_rn == "64-17-5"
    assert seen[0].method == "POST" and b"name=ethanol" in seen[0].body


def test_pubchem_not_found_is_empty():
    assert pubchem.search_compounds("nothing", client=fake_client({})) == []


def test_pubchem_bad_value_becomes_none():
    assert pubchem.parse_properties({"CID": 1, "XLogP": "n/a"}).xlogp is None


# -- NIST WebBook ---------------------------------------------------------------------------

COMPOUND = """<html><body><h1 id="Top">Water</h1><main><ul>
<li><strong>Formula:</strong> H2O</li>
<li><strong>Molecular weight:</strong> 18.0153</li>
<li><strong>CAS Registry Number:</strong> 7732-18-5</li>
<li><a href="/cgi/cbook.cgi?ID=C7732185&amp;Mask=4">Phase change data</a></li>
</ul></main></body></html>"""
PHASE = """<html><body>
<table aria-label="One dimensional data">
<tr><th>Quantity</th><th>Value</th><th>Units</th></tr>
<tr><td>Tboil</td><td>373.17 &#177; 0.04</td><td>K</td></tr>
<tr><td>Tc</td><td>647.</td><td>K</td></tr>
</table>
<table aria-label="Antoine Equation Parameters">
<tr><th>T (K)</th><th>A</th><th>B</th><th>C</th></tr>
<tr><td>255.9 to 373.</td><td>4.6543</td><td>1435.264</td><td>-64.848</td></tr>
<tr><td>379. to 573.</td><td>3.55959</td><td>643.748</td><td>-198.043</td></tr>
</table></body></html>"""


def test_nist_webbook_follows_links_and_parses_tables():
    client = fake_client({"Mask=4": (200, PHASE), "ID=C7732185&Units=SI": (200, COMPOUND)})
    found = nist_webbook.retrieve("7732-18-5", client=client)
    assert (found.name, found.cas, found.formula) == ("water", "7732-18-5", "H2O")
    assert found.temperature_boil.value == pytest.approx(373.17)
    assert [p.A for p in found.antoine_equation] == [4.6543, 3.55959]


def test_nist_webbook_without_compound_is_none():
    assert (
        nist_webbook.retrieve("unobtainium", client=fake_client({"Name=": (200, "<p/>")})) is None
    )


def test_nist_to_float():
    assert nist_webbook.to_float("1.2×10-3") == pytest.approx(0.0012)


# -- OSHA -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("-49°F", {"value": -49.0, "units": "°F"}),
        ("103 °F", {"value": 103.0, "units": "°F"}),
        ("300 K", {"value": 300.0, "units": "K"}),
        ("100-162°F", {"value": 100.0, "units": "°F", "range": [100.0, 162.0]}),
        ("−58−−40 °F", {"value": -58.0, "units": "°F", "range": [-58.0, -40.0]}),
        ("No. 2-4°F", {"value": -4.0, "units": "°F"}),
        ("1,050 °F", {"value": 1050.0, "units": "°F"}),
        ("not combustible", None),
    ],
)
def test_osha_parse_temperature(text, expected):
    assert osha.parse_temperature(text) == expected


DETAIL = """<html><body><div id="chemResultTables"><h3><strong>ACETONE</strong></h3>
<div class="table-responsive dol-table"><table class="usa-table table">
<caption><h4>Chemical Identification</h4></caption><tbody><tr><td>67-64-1</td></tr></tbody>
</table></div>
<div class="table-responsive dol-table"><table class="usa-table table">
<caption><h4>Physical Properties</h4></caption><tbody>
<tr><td>x</td></tr><tr><td>133 °F</td><td>58.1</td></tr><tr><td>-138 °F</td><td>180 mmHg</td></tr>
<tr><td>-4 °F</td><td>2.0</td></tr><tr><td>0.79</td></tr><tr><td>2.5 %</td><td>12.8 %</td></tr>
<tr><td>1</td><td>3</td></tr><tr><td>0</td></tr></tbody></table></div>
<div class="table-responsive dol-table"><table class="usa-table table">
<caption><h4>Exposure Limits</h4></caption><tbody><tr><td>h</td></tr>
<tr><td>1,000 ppm</td><td>250 ppm</td><td>250 ppm</td><td>500 ppm</td></tr></tbody></table></div>
</div></body></html>"""
SEARCH = """<table><tbody><tr>
<td class="views-field views-field-title"><a href="/chemicaldata/476">Acetone</a></td>
<td class="views-field views-field-field-cas-number">67-64-1</td></tr></tbody></table>"""


def test_osha_retrieve_finds_and_parses_the_detail_page():
    client = fake_client({"/chemicaldata/476": (200, DETAIL), "search": (200, SEARCH)})
    found = osha.retrieve("67-64-1", client=client)
    assert found["name"] == "acetone" and found["cas"] == "67-64-1"
    assert found["flash_point"] == {"value": -4.0, "units": "°F"}
    assert found["vapor_pressure"] == {"value": 180.0, "units": "mmHg"}
    assert found["lower_explosive_limit"] == {"value": 2.5, "units": "%"}
    assert found["nfpa_fire_rating"] == 3.0
    assert found["osha_twa"] == {"value": 1000.0, "units": "ppm"}
    assert found["source_url"].endswith("/chemicaldata/476")


def test_osha_unlisted_cas_stops_at_an_empty_page():
    client = fake_client({"page=0": (200, SEARCH), "page=1": (200, "<table></table>")})
    assert osha.retrieve("11-11-1", client=client) is None


ETHANOL_SEARCH = SEARCH.replace("476", "1000").replace("Acetone", "Ethanol")
ETHANOL_SEARCH = ETHANOL_SEARCH.replace("67-64-1", "64-17-5")
ETHANOL_DETAIL = DETAIL.replace("ACETONE", "ETHANOL").replace("67-64-1", "64-17-5")


def test_osha_refuses_a_name_without_walking_the_pages():
    """A name never matches the CAS column, so retrieve walked all 100
    pages."""
    seen = []
    with pytest.raises(ValueError, match="by CAS number"):
        osha.retrieve("ethanol", client=fake_client({"search": (200, ETHANOL_SEARCH)}, seen))
    assert seen == []


def test_osha_403_is_reported_once_and_plainly():
    seen = []
    client = fake_client({"osha.gov": (403, "Access Denied")}, seen)
    with pytest.raises(HttpError, match="osha.gov refused the request.*browsers only") as failure:
        osha.retrieve("64-17-5", client=client)
    assert failure.value.status == 403 and len(seen) == 1
    assert "Mozilla" not in seen[0].headers["User-Agent"]


def test_hazard_data_by_name_go_to_osha_by_the_pubchem_cas_number():
    """The name is resolved to its CAS number (PubChem) and OSHA is asked for
    that."""
    seen = []
    routes = {
        "osha.gov/chemicaldata/search": (200, ETHANOL_SEARCH),
        "osha.gov/chemicaldata/1000": (200, ETHANOL_DETAIL),
        "/compound/name/cids/JSON": (200, json.dumps({"IdentifierList": {"CID": [702]}})),
        "/property/": (200, json.dumps(PROPS)),
        "/synonyms/": (200, json.dumps(SYNONYMS)),
    }
    r = PropertyRetriever(sources={Source.PUBCHEM, Source.OSHA}, client=fake_client(routes, seen))
    found = r.get("ethanol", "lower_explosive_limit")
    assert found.ok and found.source == Source.OSHA
    assert (found.value, found.units) == (2.5, "%")
    assert found.metadata["source_url"].endswith("/chemicaldata/1000")
    assert len([q for q in seen if "osha.gov" in q.url]) == 2  # one listing page, the detail


def test_a_refused_osha_request_is_not_repeated_for_each_property():
    """get_many over the hazard fields sent one 403 request per
    field."""
    seen = []
    r = PropertyRetriever(
        sources={Source.OSHA}, client=fake_client({"osha.gov": (403, "Access Denied")}, seen)
    )
    fields = ["lower_explosive_limit", "upper_explosive_limit", "osha_twa", "idlh"]
    results = r.get_many("64-17-5", fields)
    assert all(not found.ok and "osha.gov refused" in found.error for found in results)
    assert len(seen) == 1


def test_osha_without_a_cas_number_sends_no_request():
    seen = []
    r = PropertyRetriever(sources={Source.OSHA}, client=fake_client({}, seen))
    found = r.get("ethanol", "lower_explosive_limit")
    assert not found.ok and "OSHA needs the CAS number" in found.error
    assert seen == []


def test_osha_is_not_a_source_of_the_cas_number():
    assert Source.OSHA not in SOURCE_ORDER["cas"]


# -- DDBST UNIFAC ---------------------------------------------------------------------------

UNIFAC = """<html><body>
<h3>List of Main Groups</h3><table><tr><th>No.</th><th>Maingroup Name</th></tr>
<tr><td>1</td><td>CH2</td></tr><tr><td>2</td><td>C=C</td></tr></table>
<h3>List of Sub Groups and their Group Surfaces and Volumes</h3>
<table><tr><th>Subgroup Name</th><th>Maingroup</th><th>R</th><th>Q</th></tr>
<tr><td>CH3</td><td>[1]CH2</td><td>0.9011</td><td>0.848</td></tr>
<tr><td>CH2=CH</td><td>[2]C=C</td><td>1.3454</td><td>1.176</td></tr>
<tr><td>X</td><td>[9]?</td><td>1</td><td>1</td></tr></table>
<h3>List of Interaction Parameters</h3>
<table><tr><th>i</th><th>j</th><th>Aij</th><th>Aji</th></tr>
<tr><td>1</td><td>2</td><td>86.02</td><td>-35.36</td></tr></table></body></html>"""


def test_unifac_parameters_parse():
    found = unifac.retrieve_unifac_parameters(client=fake_client({"ddbst": (200, UNIFAC)}))
    assert [(g.name, [s.name for s in g.subgroups]) for g in found.main_groups] == [
        ("CH2", ["CH3"]),
        ("C=C", ["CH2=CH"]),
    ]
    [pair] = found.interaction_parameters
    assert (pair.group_i, pair.group_j, pair.a_ij) == ("CH2", "C=C", 86.02)


def test_unifac_changed_layout_is_an_error():
    with pytest.raises(ValueError, match="layout"):
        unifac.parse_unifac_parameters("<html><body><p>moved</p></body></html>")


# -- GRAPPA / HANNA clients -----------------------------------------------------------------


def test_prediction_clients_post_to_the_given_endpoint():
    seen = []
    client = fake_client(
        {
            "/predict/vapor-pressure": (200, json.dumps([{"vapor_pressure_kPa": 7.9}])),
            "/activity_coeff": (200, json.dumps({"gamma_1": 1.2, "gamma_2": 1.5})),
        },
        seen,
    )
    grappa = prediction_services.grappa_vapor_pressure(
        "http://grappa.test/", ["CCO"], [298.15], client=client
    )
    assert grappa == [{"vapor_pressure_kPa": 7.9}]
    assert seen[0].url == "http://grappa.test/predict/vapor-pressure"
    assert json.loads(seen[0].body) == {"smiles": ["CCO"], "temperatures": [298.15]}
    hanna = prediction_services.hanna_activity_coefficients(
        "http://hanna.test", "CCO", "O", 298.15, 0.5, client=client
    )
    assert hanna["activity_coefficients"] == [1.2, 1.5]


def test_prediction_clients_validate_inputs():
    with pytest.raises(ValueError):
        prediction_services.grappa_vapor_pressure("http://g", ["CCO"], [1.0, 2.0])
    with pytest.raises(ValueError):
        prediction_services.hanna_activity_coefficients("http://h", "CCO", "O", 298.15, 1.5)


# -- the retriever --------------------------------------------------------------------------


def nist_record(**fields):
    return nist_webbook.NISTThermodynamicProperties(name="x", **fields)


def retriever(records: dict[Source, dict], **kwargs) -> PropertyRetriever:
    fetchers = {s: (lambda ident, t, p, s=s: records[s].get(ident)) for s in records}
    return PropertyRetriever(fetchers=fetchers, **kwargs)


WATER_NIST = nist_record(
    temperature_boil={"value": 373.17, "units": "K"},
    antoine_equation=[
        {"temperatures": (255.9, 373.0), "A": 4.6543, "B": 1435.264, "C": -64.848},
        {"temperatures": (379.0, 573.0), "A": 3.55959, "B": 643.748, "C": -198.043},
    ],
    source_url="https://webbook.nist.gov/water",
)
THERMO_RECORD = {
    "boiling_point": {"value": 351.4, "units": "K"},
    "vapor_pressure": {"value": 7900.0, "units": "Pa"},
    "liquid_viscosity": {"value": 1.07, "units": "mPa*s"},
    "temperature_K": 298.15,
}


def test_first_source_with_a_value_wins_and_is_named():
    r = retriever({Source.NIST: {"water": WATER_NIST}, Source.THERMO: {"ethanol": THERMO_RECORD}})
    water = r.get("water", "temperature_boil")
    assert (water.value, water.units, water.source) == (373.17, "K", Source.NIST)
    assert water.metadata["source_url"] == "https://webbook.nist.gov/water"
    ethanol = r.get("ethanol", "temperature_boil")
    assert (ethanol.value, ethanol.source) == (351.4, Source.THERMO)
    assert r.get("ethanol", "viscosity").units == "mPa*s"


def test_missing_and_unknown_properties_say_why():
    r = retriever({Source.THERMO: {}})
    assert "not found" in r.get("water", "temperature_boil").error
    assert "not a known property" in r.get("water", "colour").error


def test_antoine_set_is_chosen_by_temperature():
    r = retriever({Source.NIST: {"water": WATER_NIST}})
    low = r.get("water", "antoine_parameters", 300.0).value
    high = r.get("water", "antoine_parameters", 400.0).value
    assert (low["A"], high["A"], low["equation"]) == (4.6543, 3.55959, ANTOINE_FORM)
    extrapolated = r.get("water", "antoine_parameters", 200.0).value
    assert extrapolated["A"] == 4.6543 and "extrapolated" in extrapolated["note"]


def test_nist_vapor_pressure_only_inside_the_antoine_range():
    r = retriever({Source.NIST: {"water": WATER_NIST}, Source.THERMO: {"water": THERMO_RECORD}})
    inside = r.get("water", "vapor_pressure", 350.0)  # steam tables: 41.68 kPa
    assert inside.source == Source.NIST and inside.value == pytest.approx(41680, rel=0.01)
    assert r.get("water", "vapor_pressure", 200.0).source == Source.THERMO


def test_failing_source_falls_through_and_is_reported():
    def broken(*_):
        raise HttpError("down", url="u")

    r = PropertyRetriever(fetchers={Source.NIST: broken, Source.THERMO: lambda *_: None})
    found = r.get("water", "temperature_boil")
    assert not found.ok and "down" in found.error


def test_records_are_fetched_once_per_instance():
    calls = []

    def nist(ident, t, p):
        calls.append(ident)
        return WATER_NIST

    r = PropertyRetriever(fetchers={Source.NIST: nist})
    r.get_many("water", ["temperature_boil", "antoine_a", "antoine_b"])
    assert calls == ["water"]


def test_sources_can_be_restricted():
    r = retriever(
        {Source.NIST: {"water": WATER_NIST}, Source.THERMO: {"water": THERMO_RECORD}},
        sources={Source.THERMO},
    )
    assert r.get("water", "temperature_boil").source == Source.THERMO


def test_grappa_is_asked_last_and_only_with_an_endpoint():
    routes = {
        "/predict/antoine-parameters": (
            200,
            json.dumps([{"antoine_A": 16.5, "antoine_B": 3600.0, "antoine_C": -50.0}]),
        )
    }
    pubchem_record = pubchem.PubChemProperties(cid=1, canonical_smiles="CCO")
    fetchers = {Source.PUBCHEM: lambda *_: pubchem_record, Source.NIST: lambda *_: None}
    assert not PropertyRetriever(fetchers=fetchers).get("ethanol", "antoine_a").ok
    r = PropertyRetriever(
        fetchers=fetchers, grappa_endpoint="http://grappa.test", client=fake_client(routes)
    )
    found = r.get("ethanol", "antoine_parameters").value
    a, b, c = grappa_antoine_to_canonical(16.5, 3600.0, -50.0)
    assert (found["A"], found["B"], found["C"]) == (a, b, c)
    assert r.get("ethanol", "antoine_parameters").source == Source.GRAPPA


def test_grappa_antoine_conversion_gives_the_same_pressure():
    a, b, c = 16.0, 3800.0, -45.0
    t = 350.0
    kpa = math.exp(a - b / (t + c))
    a2, b2, c2 = grappa_antoine_to_canonical(a, b, c)
    assert 10 ** (a2 - b2 / (t + c2)) * 100 == pytest.approx(kpa)


def test_relative_volatility_ideal_and_boiling_point_difference():
    benzene = {
        "vapor_pressure": {"value": 12.7, "units": "kPa"},
        "boiling_point": {"value": 353.2, "units": "K"},
    }
    toluene = {
        "vapor_pressure": {"value": 3790.0, "units": "Pa"},
        "boiling_point": {"value": 383.8, "units": "K"},
    }
    r = retriever({Source.THERMO: {"benzene": benzene, "toluene": toluene}})
    alpha = r.mixture("benzene", "toluene", "relative_volatility")
    assert alpha.value == pytest.approx(12700 / 3790) and alpha.metadata["ideal"] is True
    assert alpha.source == Source.DERIVED
    delta = r.mixture("benzene", "toluene", "boiling_point_difference")
    assert (delta.value, delta.units) == (pytest.approx(30.6), "K")


def test_relative_volatility_uses_hanna_when_given():
    records = {
        "a": {"vapor_pressure": {"value": 2.0, "units": "Pa"}},
        "b": {"vapor_pressure": {"value": 1.0, "units": "Pa"}},
    }
    client = fake_client({"/activity_coeff": (200, json.dumps({"gamma_1": 3.0, "gamma_2": 1.5}))})
    r = retriever({Source.THERMO: records}, hanna_endpoint="http://hanna.test", client=client)
    alpha = r.mixture("a", "b", "relative_volatility", x1=0.5, smiles_1="CCO", smiles_2="O")
    assert alpha.value == pytest.approx(4.0) and alpha.metadata["ideal"] is False
    assert relative_volatility(2.0, 1.0, 3.0, 1.5) == pytest.approx(4.0)


def test_mixture_failures_are_results_not_exceptions():
    r = retriever({Source.THERMO: {}})
    assert "HANNA endpoint" in r.mixture("a", "b", "activity_coefficient", x1=0.5).error
    assert "Cannot compute" in r.mixture("a", "b", "relative_volatility").error
    assert "not a binary property" in r.mixture("a", "b", "colour").error


def test_retrieve_properties_converts_the_conditions():
    seen = []

    def thermo(ident, t, p):
        seen.append((t, p))
        return THERMO_RECORD

    r = PropertyRetriever(fetchers={Source.THERMO: thermo}, sources={Source.THERMO})
    [found] = retrieve_properties(
        "ethanol",
        ["viscosity"],
        temperature=25,
        temperature_unit="°C",
        pressure=1,
        pressure_unit="bar",
        retriever=r,
    )
    assert found.ok and seen == [(pytest.approx(298.15), pytest.approx(1e5))]


def test_thermo_adapter_gives_water_properties():
    pytest.importorskip("thermo")
    from chemeascode.integrations.thermo import chemical_properties

    found = chemical_properties("water", 298.15, 101325.0)
    assert found["boiling_point"]["value"] == pytest.approx(373.1, abs=0.5)
    assert found["phase"] == "liquid" and found["cp_liquid"]["value"] == pytest.approx(75.3, abs=1)
    with pytest.raises(ValueError):
        chemical_properties("no-such-compound-xyz")
