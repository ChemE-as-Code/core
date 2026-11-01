"""Regional LCI scenarios and design cases without duplicating plants.

The plant is ``tests/data/lca-scenarios-asu``: a SYNTHETIC ASU-like flowsheet (GOX, GAN, LOX,
LIN, 10,000 kW of electric power, 9,000 kW to cooling water; a separately computed ``hot`` case
with 11,000 kW), the packaged DESNZ UK grid as the baseline's proxy, and synthetic NL and DE
grid factors marked synthetic. No network, no Brightway, no licensed data.
"""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.domains.assessment.lca.scenarios import (
    RECORD_SCHEMA,
    compare_cases,
    record,
    records,
)
from chemeascode.domains.assessment.lca.schemas import Scenario
from chemeascode.interfaces.cli import app

FIXTURE = Path(__file__).parent / "data" / "lca-scenarios-asu"
UK_GRID = "desnz-ghg-2026:electricity-gb"
GOX, PRODUCTS = 20860.0, 20860.0 + 12510.0 + 600.0 + 600.0


@pytest.fixture
def asu(tmp_path: Path) -> Path:
    root = tmp_path / "asu"
    shutil.copytree(FIXTURE, root)
    return root


def _edit(root: Path, name: str, change) -> None:
    path = root / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _report(root: Path):
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    return report


def _link(data: dict, key: str) -> dict:
    return next(e for e in data["linked_inventory"]["exchanges"] if e["key"] == key)


def _amount(data: dict, key: str) -> float:
    return next(e["amount"] for e in data["foreground"]["exchanges"] if e["key"] == key)


def _power(report, scenario: str) -> float:
    return sum(i.value for i in report.impacts if i.scenario == scenario and i.key == "feed:POWER")


# -- one foreground, several regional backgrounds ---------------------------------------------


def test_one_case_yields_identifiable_regional_scenarios(asu: Path) -> None:
    report = _report(asu)
    files = records(report)
    assert list(files) == [
        "lca/scenarios/baseline.json",
        "lca/scenarios/nl-grid-2025.json",
        "lca/scenarios/de-grid-2025.json",
        "lca/scenarios/nl-ppa.json",
        "lca/scenarios/hot-climate.json",
    ]
    data = {p: json.loads(t) for p, t in files.items()}
    ids = [d["id"] for d in data.values()]
    assert len(set(ids)) == len(ids)
    nl = data["lca/scenarios/nl-grid-2025.json"]
    assert nl["schema"] == RECORD_SCHEMA
    assert nl["id"] == "synthetic-asu-scenario-fixture/design/nl-grid-2025"
    assert nl["scenario"]["kind"] == "background"
    assert (nl["scenario"]["location"], nl["scenario"]["year"]) == ("NL", 2025)
    assert nl["scenario"]["electricity"] == "grid-average"
    assert nl["design_case"]["id"] == "design"
    assert nl["design_case"]["capacity"] == "500 t/d GOX"
    # the three layers are labelled and kept apart
    assert nl["foreground"]["layer"] == "foreground"
    assert nl["foreground"]["basis"] == "1 h of operation"
    assert nl["linked_inventory"]["layer"] == "linked-inventory"
    assert nl["impacts"]["layer"] == "characterized-impact"


def test_a_region_swap_changes_the_background_not_the_foreground(asu: Path) -> None:
    report = _report(asu)
    base, nl, de = (record(report, s) for s in ("baseline", "nl-grid-2025", "de-grid-2025"))
    # the same foreground: physical flows and energy unchanged, the same fingerprint
    assert base["foreground"]["fingerprint"] == nl["foreground"]["fingerprint"]
    assert nl["foreground"]["fingerprint"] == de["foreground"]["fingerprint"]
    assert _amount(base, "feed:POWER") == _amount(nl, "feed:POWER") == 10000.0
    assert nl["foreground"]["relation"] == "unchanged"
    assert any("physical flows and duties are unchanged" in n for n in nl["notes"])
    # the electricity link names the actual factor of each scenario, quantity and unit kept
    power = _link(nl, "feed:POWER")
    assert power["background"] == "electricity-nl-synthetic"
    assert power["baseline"] == f"factor:{UK_GRID}"
    assert power["replaced"] is True
    assert (power["amount"], power["unit"]) == (10000.0, "kWh")
    assert (power["location"], power["year"], power["state"]) == ("NL", 2025, "linked")
    assert power["source_id"] == "synthetic-test"
    assert _link(base, "feed:POWER")["state"] == "proxy"
    assert _link(base, "feed:POWER")["location"] == "GB"
    # the characterised contribution changes with the factor only
    per_fu_kwh = 10000.0 * (GOX / PRODUCTS) * 1000.0 / GOX
    assert _power(report, "nl-grid-2025") == pytest.approx(per_fu_kwh * 0.30)
    assert _power(report, "de-grid-2025") == pytest.approx(per_fu_kwh * 0.40)
    assert _power(report, "baseline") == pytest.approx(per_fu_kwh * 0.18436)


def test_the_baseline_uk_proxy_kept_in_another_region_warns(asu: Path) -> None:
    # an NL scenario that does not replace the UK grid: named, never relabelled NL
    def change(data):
        data["scenarios"].append(
            {
                "id": "nl-cooling-only",
                "location": "NL",
                "year": 2025,
                "factors": {"cooling-water": "electricity-nl-synthetic"},
                "source": "test",
            }
        )

    _edit(asu, "lca/lca.yaml", change)
    report = lca_report(asu)
    rules = {(f.rule, tuple(f.ids)) for f in report.findings}
    assert ("cheme.lca-scenario-geography", ("nl-cooling-only", UK_GRID)) in rules
    data = record(report, "nl-cooling-only")
    power = _link(data, "feed:POWER")
    assert (power["background"], power["location"], power["replaced"]) == (UK_GRID, "GB", False)
    assert power["state"] == "proxy"
    assert any(w["rule"] == "cheme.lca-scenario-geography" for w in data["warnings"])
    assert "geography mismatch" in data["impacts"]["reasons"]
    # the other scenarios' records do not carry that warning
    assert not any(
        w["rule"] == "cheme.lca-scenario-geography"
        for w in record(report, "de-grid-2025")["warnings"]
    )


def test_a_scenario_proxy_declaration_discloses_the_foreign_background(asu: Path) -> None:
    report = _report(asu)
    nl, ppa = record(report, "nl-grid-2025"), record(report, "nl-ppa")
    # nl-grid-2025 keeps the UK cooling estimate silently: warned
    assert any(
        w["rule"] == "cheme.lca-scenario-geography" and "cooling-water" in w["message"]
        for w in nl["warnings"]
    )
    # nl-ppa declares it a proxy: marked PROXY, no geography warning
    cooling = _link(ppa, "product:CW")
    assert (cooling["state"], cooling["note"]) == ("proxy", "UK cooling estimate stands in for NL")
    assert not any(w["rule"] == "cheme.lca-scenario-geography" for w in ppa["warnings"])
    assert ppa["scenario"]["electricity"] == "contractual"
    assert ppa["impacts"]["classification"] == "screening"


def test_missing_regional_data_is_a_gap_never_zero(asu: Path) -> None:
    report = _report(asu)
    de = record(report, "de-grid-2025")
    cooling = _link(de, "product:CW")
    assert cooling["state"] == "missing"
    assert cooling["note"] == "no DE cooling water factor available"
    assert cooling["amount"] == 9000.0  # quantity kept
    (gap,) = [g for g in de["gaps"] if g["key"] == "product:CW"]
    assert gap["reason"] == "missing" and gap["quantity"] > 0
    assert de["impacts"]["classification"] == "partial"
    # the baseline characterises cooling water: the DE total does not compare with it
    assert (de["impacts"]["comparable"], de["impacts"]["dropped"]) == (False, ["product:CW"])
    assert record(report, "nl-grid-2025")["impacts"]["comparable"] is True
    # no total without it (null, never a lower number); the characterised sum stays separate
    assert de["impacts"]["totals"]["climate-change"] is None
    assert de["impacts"]["characterised_sum"]["climate-change"] == pytest.approx(
        _power(report, "de-grid-2025"), rel=1e-5
    )
    # the baseline still characterises cooling water: no leakage
    assert _link(record(report, "baseline"), "product:CW")["state"] == "linked"


def test_an_unknown_regional_factor_is_an_error_not_a_zero(asu: Path) -> None:
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d["scenarios"][0].update({"factors": {UK_GRID: "electricity-fr"}}),
    )
    report = lca_report(asu)
    assert not report.loaded
    assert any(
        f.rule == "cheme.lca-factor-unknown" and "electricity-fr" in f.message
        for f in report.findings
    )


def test_a_missing_or_proxy_key_naming_no_exchange_warns(asu: Path) -> None:
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d["scenarios"][1].update({"missing": {"feed:STEAM": "none"}}),
    )
    report = lca_report(asu)
    assert any(
        f.rule == "cheme.lca-scenario-key" and "feed:STEAM" in f.message for f in report.findings
    )


def test_a_mismatched_scenario_year_is_flagged(asu: Path) -> None:
    _edit(asu, "lca/lca.yaml", lambda d: d["scenarios"][0].update({"year": 2040}))
    report = _report(asu)
    data = record(report, "nl-grid-2025")
    assert any(
        w["rule"] == "cheme.lca-scenario-year" and "electricity-nl-synthetic" in w["message"]
        for w in data["warnings"]
    )
    assert "reference year mismatch" in data["impacts"]["reasons"]


def test_restricted_background_terms_survive_into_the_record(asu: Path) -> None:
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: d["sources"][0].update({"publication": "restricted", "licence": "vendor EULA"}),
    )
    report = _report(asu)
    nl = record(report, "nl-grid-2025")
    assert nl["publication"] == {
        "policy": "restricted",
        "publishable": False,
        "restricted_by": ["synthetic-test"],
    }
    assert nl["inputs"]["background"]["sources"]


# -- reproducibility and staleness ----------------------------------------------------------


def test_records_are_deterministic_and_carry_no_time(asu: Path) -> None:
    first = records(_report(asu))
    second = records(_report(asu))
    assert first == second
    text = "".join(first.values())
    assert str(asu) not in text and "commit" not in text
    data = json.loads(first["lca/scenarios/nl-grid-2025.json"])
    assert set(data["inputs"]) == {"files", "mapping", "scenario", "background", "software"}
    assert data["inputs"]["files"]["lca/factors.yaml"].startswith("sha256:")


def test_scenarios_do_not_leak_into_each_other(asu: Path) -> None:
    report = _report(asu)
    # the baseline's inventory is untouched by the scenarios' missing:, proxy: and cases
    assert report.inventory.backgrounds["product:CW"].factor == "cooling-water"
    assert report.inventory.backgrounds["feed:POWER"].proxy
    assert report.inventory.case == "design"
    baseline = record(report, "baseline")

    def drop(data):
        data["scenarios"] = []

    _edit(asu, "lca/lca.yaml", drop)
    alone = record(_report(asu), "baseline")
    # the same baseline with or without scenarios (the inputs' lca.yaml hash aside)
    for part in ("foreground", "linked_inventory", "impacts", "gaps", "publication"):
        assert alone[part] == baseline[part]


def test_a_changed_factor_or_database_makes_the_records_stale(asu: Path, monkeypatch) -> None:
    monkeypatch.chdir(asu)
    runner = CliRunner()
    result = runner.invoke(app, ["assess", "lca-scenarios", "--write"])
    assert result.exit_code == 0, result.output
    assert (asu / "lca/scenarios/nl-grid-2025.json").is_file()
    assert runner.invoke(app, ["assess", "lca-scenarios", "--check"]).exit_code == 0
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: d["factors"][0]["values"].update({"climate-change": 0.31}),
    )
    result = runner.invoke(app, ["assess", "lca-scenarios", "--check"])
    assert result.exit_code == 1
    assert "lca/scenarios/nl-grid-2025.json is not current" in result.output


def test_cli_summary_json_and_unknown_scenario(asu: Path, monkeypatch) -> None:
    monkeypatch.chdir(asu)
    runner = CliRunner()
    result = runner.invoke(app, ["assess", "lca-scenarios", "de-grid-2025"])
    assert result.exit_code == 0, result.output
    assert "foreground unchanged" in result.output
    assert "product:CW: missing" in result.output
    result = runner.invoke(app, ["assess", "lca-scenarios", "nl-ppa", "--json"])
    assert json.loads(result.stdout)["lca/scenarios/nl-ppa.json"]["scenario"]["id"] == "nl-ppa"
    result = runner.invoke(app, ["assess", "lca-scenarios", "fr-grid"])
    assert result.exit_code == 2
    assert "unknown scenario fr-grid" in result.output


# -- design cases: computed, never scaled --------------------------------------------------


def test_a_physical_change_needs_its_own_computed_case(asu: Path) -> None:
    report = _report(asu)
    hot, base = record(report, "hot-climate"), record(report, "baseline")
    assert hot["scenario"]["kind"] == "design-case"
    assert hot["foreground"]["relation"] == "design-case"
    assert hot["id"] == "synthetic-asu-scenario-fixture/hot/hot-climate"
    assert hot["design_case"]["id"] == "hot"
    assert _amount(hot, "feed:POWER") == 11000.0
    assert _amount(base, "feed:POWER") == 10000.0
    assert hot["foreground"]["fingerprint"] != base["foreground"]["fingerprint"]
    assert any("not scaled from the baseline" in n for n in hot["notes"])


def test_a_scenario_case_must_exist(asu: Path) -> None:
    _edit(asu, "lca/lca.yaml", lambda d: d["scenarios"][3].update({"case": "2000-t-d"}))
    report = lca_report(asu)
    assert not report.loaded
    assert any(f.rule == "cheme.lca-case" and "hot-climate" in f.message for f in report.findings)


def test_compare_cases_only_existing_cases(asu: Path) -> None:
    rows, findings = compare_cases(asu)
    assert not findings
    assert [r["case"] for r in rows] == ["design", "hot"]
    design, hot = rows
    assert design["capacity"] == "500 t/d GOX" and design["provenance"] == "assumed"
    assert design["applicability"]["range"].startswith("450-550")
    assert design["per_unit"]["feed:POWER"]["amount"] == pytest.approx(10000 / GOX, rel=1e-5)
    assert hot["per_unit"]["feed:POWER"]["amount"] == pytest.approx(11000 / GOX, rel=1e-5)
    # a capacity nobody computed is refused, never interpolated
    rows, findings = compare_cases(asu, ["design", "2000-t-d"])
    assert [r["case"] for r in rows] == ["design"]
    assert any(f.rule == "cheme.lca-case" and "2000-t-d" in f.message for f in findings)


def test_an_extrapolated_case_is_labelled(asu: Path) -> None:
    def change(data):
        data["cases"][1]["provenance"] = "extrapolated"

    _edit(asu, "process/flowsheet.yaml", change)
    rows, _ = compare_cases(asu, ["hot"])
    assert rows[0]["extrapolated"] is True
    hot = record(_report(asu), "hot-climate")
    assert hot["design_case"]["extrapolated"] is True
    assert any("not a predictive or validated design" in n for n in hot["notes"])


# -- allocation stays separate -------------------------------------------------------------


def test_coproducts_stay_unallocated_and_the_gox_unit_is_explicit(asu: Path) -> None:
    report = _report(asu)
    nl = record(report, "nl-grid-2025")
    products = {e["key"] for e in nl["foreground"]["exchanges"] if e["type"] == "product"}
    assert products == {"product:GOXP", "product:GANP", "product:LOX", "product:LIN"}
    impacts = nl["impacts"]
    assert impacts["functional_unit"] == {
        "product": "GOXP",
        "amount": 1,
        "unit": "t",
        "kg": 1000,
        # any reference unit
        "reference_amount": {"value": 1000, "unit": "kg"},
    }
    assert impacts["allocation"]["method"] == "mass"
    shares = impacts["allocation"]["shares"]
    assert shares["GOXP"] == pytest.approx(GOX / PRODUCTS, rel=1e-5)
    assert sum(shares.values()) == pytest.approx(1.0, rel=1e-5)
    # the foreground stays per hour of the whole plant, not per kg oxygen
    assert _amount(nl, "feed:POWER") == 10000.0


def test_allocation_choice_changes_the_impact_not_the_inventory(asu: Path) -> None:
    mass = _report(asu)
    _edit(asu, "lca/lca.yaml", lambda d: d["allocation"].update({"method": "none"}))
    none = _report(asu)
    m, n = record(mass, "nl-grid-2025"), record(none, "nl-grid-2025")
    assert m["foreground"]["fingerprint"] == n["foreground"]["fingerprint"]
    assert n["impacts"]["allocation"]["method"] == "none"
    assert n["impacts"]["totals"]["climate-change"] == pytest.approx(
        m["impacts"]["totals"]["climate-change"] * PRODUCTS / GOX, rel=1e-5
    )


# -- compatibility -------------------------------------------------------------------------


def test_scenarios_without_a_location_keep_their_former_behaviour(asu: Path) -> None:
    # a former-style scenario (no location): the mapping's proxy marker stays, as before
    def change(data):
        data["scenarios"] = [
            {"id": "grid-2040", "factors": {UK_GRID: "electricity-nl-synthetic"}, "source": "t"}
        ]

    _edit(asu, "lca/lca.yaml", change)
    report = _report(asu)
    power = [i for i in report.impacts if i.scenario == "grid-2040" and i.key == "feed:POWER"]
    assert power[0].status == "PROXY"
    assert not any(f.rule.startswith("cheme.lca-scenario-") for f in report.findings)
    assert report.payload()["scenario_ids"] == ["baseline", "grid-2040"]


def test_scenario_schema_checks() -> None:
    with pytest.raises(ValidationError, match="contractual"):
        Scenario(id="ppa", electricity="contractual")
    with pytest.raises(ValidationError, match="missing and proxy"):
        Scenario(id="x", missing={"feed:A": "a"}, proxy={"feed:A": "b"})
    assert not Scenario(id="old", factors={"a": "b"}).regional
    assert Scenario(id="nl", location="NL").regional


def test_the_fixture_factors_are_marked_synthetic() -> None:
    factors = yaml.safe_load((FIXTURE / "lca/factors.yaml").read_text(encoding="utf-8"))
    regional = [f for f in factors["factors"] if f["id"].startswith("electricity-")]
    assert regional and all("SYNTHETIC" in f["title"] for f in regional)
    assert copy.deepcopy(factors["sources"][0])["title"].startswith("Synthetic")


# -- review fixes: no zero totals from gaps, findings stay with their scenario ---------------


def _second_category(root: Path) -> None:
    def change(data):
        data["categories"].append({"id": "acid", "unit": "mol H+-eq"})
        cooling = next(f for f in data["factors"] if f["id"] == "cooling-water")
        cooling["values"]["acid"] = 0.5
        data["factors"].append(
            {**cooling, "id": "cooling-nl", "values": {"climate-change": 1.0}, "location": "NL"}
        )

    _edit(root, "lca/factors.yaml", change)


def test_a_category_with_a_gap_has_no_total_not_zero(asu: Path) -> None:
    _second_category(asu)
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d["scenarios"][0]["factors"].update({"cooling-water": "cooling-nl"}),
    )
    report = _report(asu)
    base, nl = record(report, "baseline"), record(report, "nl-grid-2025")
    assert base["impacts"]["totals"]["acid"] > 0
    # cooling-nl has no acid value: the NL acid total is unknown, not 0
    assert nl["impacts"]["totals"]["acid"] is None
    assert nl["impacts"]["totals"]["climate-change"] > 0
    assert nl["impacts"]["dropped_by_category"] == {"acid": ["product:CW"]}
    assert nl["impacts"]["comparable"] is False
    # the UK grid has no acid value: the baseline's acid total excludes it, marked partial
    assert base["impacts"]["partial_categories"] == ["acid"]
    assert base["impacts"]["comparable"] is True
    # the factor-category warning is the NL scenario's, not the baseline's
    assert any("cooling-nl" in w["message"] for w in nl["warnings"])
    assert not any("cooling-nl" in w["message"] for w in base["warnings"])


def test_a_scenario_with_everything_missing_has_no_total(asu: Path) -> None:
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d["scenarios"][1].update(
            {"missing": {"feed:POWER": "none", "product:CW": "none"}, "factors": {}}
        ),
    )
    data = record(_report(asu), "de-grid-2025")
    assert data["impacts"]["totals"] == {"climate-change": None}
    assert data["impacts"]["comparable"] is False


def test_a_design_case_keeps_its_own_inventory_warnings(asu: Path) -> None:
    def change(data):
        q1 = next(s for s in data["streams"] if s["id"] == "Q1")
        del q1["state"]["hot"]

    _edit(asu, "process/flowsheet.yaml", change)
    report = _report(asu)
    hot, base = record(report, "hot-climate"), record(report, "baseline")
    assert any("scenario hot-climate (case hot)" in w["message"] for w in hot["warnings"]), hot[
        "warnings"
    ]
    assert not any("case hot" in w["message"] for w in base["warnings"])


def test_a_year_without_location_is_still_checked(asu: Path) -> None:
    def change(data):
        data["scenarios"].append(
            {
                "id": "grid-2050",
                "year": 2050,
                "factors": {UK_GRID: "electricity-nl-synthetic"},
                "source": "t",
            }
        )

    _edit(asu, "lca/lca.yaml", change)
    report = _report(asu)
    assert any(
        f.rule == "cheme.lca-scenario-year" and "grid-2050" in f.ids for f in report.findings
    )
    assert not any(
        f.rule == "cheme.lca-scenario-geography" and "grid-2050" in f.ids for f in report.findings
    )


def test_records_of_removed_scenarios_are_stale(asu: Path, monkeypatch) -> None:
    monkeypatch.chdir(asu)
    runner = CliRunner()
    assert runner.invoke(app, ["assess", "lca-scenarios", "--write"]).exit_code == 0
    _edit(asu, "lca/lca.yaml", lambda d: d.update({"scenarios": d["scenarios"][:1]}))
    result = runner.invoke(app, ["assess", "lca-scenarios", "--check"])
    assert result.exit_code == 1
    assert "lca/scenarios/de-grid-2025.json is no scenario" in result.output
    result = runner.invoke(app, ["assess", "lca-scenarios", "--write"])
    assert "removed lca/scenarios/de-grid-2025.json" in result.output
    assert not (asu / "lca/scenarios/de-grid-2025.json").exists()
    assert runner.invoke(app, ["assess", "lca-scenarios", "--check"]).exit_code == 0


def test_compare_cases_never_reports_a_missing_product_as_zero(asu: Path) -> None:
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d.update({"functional_unit": {"product": "LIN", "amount": 1, "unit": "t"}}),
    )

    def change(data):
        s5 = next(s for s in data["streams"] if s["id"] == "S5")
        s5["state"]["hot"]["flow"]["value"] = 0

    _edit(asu, "process/flowsheet.yaml", change)
    rows, _ = compare_cases(asu)
    hot = next(r for r in rows if r["case"] == "hot")
    assert hot["per_unit"] == {} or all(v is None for v in hot["per_unit"].values())
    assert "unknown" in hot


def test_results_and_api_mark_totals_that_do_not_stand(asu: Path) -> None:
    from chemeascode.domains.assessment.lca.report import results_markdown

    report = _report(asu)
    assert report.payload()["not_comparable"] == {
        "de-grid-2025": {"climate-change": ["product:CW"]}
    }
    text = results_markdown(report)
    assert "not comparable (no background for product:CW)" in text
    # the other scenarios keep their numbers
    assert f"{report.totals('nl-grid-2025')['climate-change']:.6g}" in text
