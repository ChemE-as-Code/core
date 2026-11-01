"""Structured factor scope, the method-mix check and the scenario comparability verdict.
One test per comparison dimension; no network, no licensed data."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca import backgrounds
from chemeascode.domains.assessment.lca.backgrounds import profile
from chemeascode.domains.assessment.lca.comparability import (
    differences,
    effective_scope,
)
from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.domains.assessment.lca.scenarios import record
from chemeascode.domains.assessment.lca.schemas import FactorFile, FactorScope

FIXTURE = Path(__file__).parent / "data" / "lca-scenarios-asu"
UK = "desnz-ghg-2026:electricity-gb"


def _s(**kw) -> tuple[FactorScope, int | None]:
    year = kw.pop("year", 2025)
    return FactorScope(**kw), year


FULL = {
    "basis": "direct",
    "delivery": "generation",
    "gases": "co2e",
    "gwp": "AR5",
    "mix": "grid-average",
    "accounting": "generation",
}


def _dims(a, b) -> dict[str, dict]:
    return {d["dimension"]: d for d in differences(a, b)}


def test_identical_declared_scopes_differ_nowhere() -> None:
    assert differences(_s(**FULL), _s(**FULL)) == []


@pytest.mark.parametrize(
    ("dimension", "other", "severity"),
    [
        ("basis", "life-cycle", "hard"),
        ("gases", "co2", "hard"),
        ("accounting", "consumption", "hard"),
        ("delivery", "consumer", "soft"),
        ("gwp", "AR6", "soft"),
        ("mix", "residual-mix", "soft"),
    ],
)
def test_each_scope_dimension_is_detected(dimension: str, other: str, severity: str) -> None:
    changed = {**FULL, dimension: other}
    found = _dims(_s(**FULL), _s(**changed))
    assert found[dimension]["kind"] == "differs"
    assert found[dimension]["severity"] == severity
    if dimension == "gases":  # CO2 only: the GWP basis does not apply
        assert set(found) == {"gases"}
    else:
        assert set(found) == {dimension}


def test_data_year_is_a_soft_dimension() -> None:
    found = _dims(_s(**FULL, year=2024), _s(**FULL, year=2025))
    assert set(found) == {"year"} and found["year"]["severity"] == "soft"


def test_an_undeclared_dimension_is_never_assumed_equal() -> None:
    found = _dims(_s(**FULL), _s(**{**FULL, "gwp": None}))
    assert found["gwp"]["kind"] == "undeclared" and found["gwp"]["severity"] == "soft"
    assert set(_dims(_s(), _s())) >= {"basis", "delivery", "gases", "mix", "accounting"}


# -- packaged profiles: scope as data, profile files byte-stable --------------------------------


def test_packaged_profiles_carry_a_scope_without_changing_their_files() -> None:
    # fingerprints of the profile files are what projects' manifests record: the sidecar keeps
    # them; the checksums below are of the files as merged before the scopes were added
    checksums = {
        "desnz-ghg-2026": "6d7cd7e8f75e2e921a0952c7f815ee78cb4144f447530043c465e83f5b98b3b1",
        "eea-ener038-2024": "7654ee133a8be4d05c9694e06455583f934726b0c8a7bc3e91d639af18af6738",
        "egrid-2023": "3e2d08ac4dbd8b32d8938cdb8e6402bde2c63feb59a9dbda4dc08f1297cb0c3f",
        "ember-2025": "59a236406dd7d7778927977d471d3493a3a9da53d22d25affcd0eaf9751c6bfc",
        "uba-strommix-2026": "a55cfc651d2698d97098731ae5bc65e44b31d3c5eed9873aeaff79c72aa62168",
    }
    for name, digest in checksums.items():
        assert hashlib.sha256((backgrounds.DATA / f"{name}.yaml").read_bytes()).hexdigest() == (
            digest
        ), name
    expected = {
        "egrid-2023": ("direct", "generation", "co2e", "AR5"),
        "eea-ener038-2024": ("direct", "generation", "co2e", None),
        "ember-2025": ("life-cycle", "generation", "co2e", "mixed"),
        "uba-strommix-2026": ("direct", "consumer", "co2", None),
    }
    for name, (basis, delivery, gases, gwp) in expected.items():
        data = profile(name)
        for factor in data.factors:
            scope, _ = effective_scope(data, factor.id)
            assert (scope.basis, scope.delivery, scope.gases, scope.gwp) == (
                basis,
                delivery,
                gases,
                gwp,
            ), factor.id
        text = (backgrounds.DATA / f"{name}.yaml").read_text(encoding="utf-8")
        assert "scope:" not in text  # the profile file itself was not edited
    desnz = profile("desnz-ghg-2026")
    scope, year = effective_scope(desnz, "electricity-gb")
    assert (scope.basis, scope.delivery, scope.gases, scope.gwp) == (
        "direct+upstream",
        "consumer",
        "co2e",
        "AR4/AR5",
    )
    assert scope.accounting is None  # not stated by the profile: undeclared, not guessed


def test_a_scope_in_the_profile_file_wins_over_the_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "p.yaml"
    sidecar.write_text("sources:\n  s: {basis: direct, gases: co2e}\n", encoding="utf-8")
    data = FactorFile.model_validate(
        {
            "schema": "cheme/lca/v1",
            "kind": "lca_factors",
            "sources": [
                {
                    "id": "s",
                    "title": "a source",
                    "provider": "me",
                    "version": "1",
                    "licence": "CC0-1.0",
                    "publication": "public",
                    "scope": {"basis": "life-cycle"},
                }
            ],
            "categories": [{"id": "climate-change", "unit": "kg CO2-eq"}],
        }
    )
    merged = backgrounds._scoped(data, sidecar)
    assert (merged.sources[0].scope.basis, merged.sources[0].scope.gases) == ("life-cycle", "co2e")


def test_a_factor_scope_overrides_its_source_field_by_field() -> None:
    data = FactorFile.model_validate(
        {
            "schema": "cheme/lca/v1",
            "kind": "lca_factors",
            "sources": [
                {
                    "id": "s",
                    "title": "a source",
                    "provider": "me",
                    "version": "1",
                    "licence": "CC0-1.0",
                    "publication": "public",
                    "scope": {"basis": "direct", "gases": "co2e"},
                }
            ],
            "categories": [{"id": "c", "unit": "kg CO2-eq"}],
            "factors": [
                {
                    "id": "f",
                    "unit": "kWh",
                    "values": {"c": 1.0},
                    "status": "PUBLISHED",
                    "source": "x y z",
                    "source_id": "s",
                    "year": 2024,
                    "scope": {"delivery": "consumer"},
                }
            ],
        }
    )
    scope, year = effective_scope(data, "f")
    assert (scope.basis, scope.gases, scope.delivery, year) == ("direct", "co2e", "consumer", 2024)


def test_existing_factor_files_without_scope_still_load() -> None:
    text = (FIXTURE / "lca/factors.yaml").read_text(encoding="utf-8")
    assert FactorFile.model_validate(yaml.safe_load(text)).factors


# -- scenario verdicts and method-mix on a real report ------------------------------------------


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


def _with_profiles(root: Path, profiles: list[str], replacement: str | None, year=None) -> None:
    _edit(root, "lca/factors.yaml", lambda d: d.update(include=profiles))
    if replacement:

        def scenario(d):
            nl = next(s for s in d["scenarios"] if s["id"] == "nl-grid-2025")
            nl["factors"] = {UK: replacement}
            nl["proxy"] = {}
            if year:
                nl["year"] = year

        _edit(root, "lca/lca.yaml", scenario)


def _verdict(root: Path, scenario: str = "nl-grid-2025") -> dict:
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    return record(report, scenario)["comparability"]


def test_baseline_is_its_own_reference(asu: Path) -> None:
    assert _verdict(asu, "baseline")["verdict"] == "baseline"


def test_uk_against_eea_is_not_comparable_on_basis(asu: Path) -> None:
    # DESNZ includes well-to-tank (direct+upstream), EEA is direct: the ASU's NL/DE case
    _with_profiles(asu, ["desnz-ghg-2026", "eea-ener038-2024"], "eea-ener038-2024:electricity-nl")
    v = _verdict(asu)
    assert v["verdict"] == "not comparable"
    assert any("basis differs" in r for r in v["reasons"])
    diffs = {d["dimension"] for c in v["compared"] for d in c["differences"]}
    assert {"basis", "delivery"} <= diffs
    # the gwp basis of EEA is undeclared (inferred only): never assumed equal
    assert any(
        d["dimension"] == "gwp" and d["kind"] == "undeclared"
        for c in v["compared"]
        for d in c["differences"]
    )


def test_eea_against_ember_basis_and_uba_gases_are_hard() -> None:
    eea = effective_scope(profile("eea-ener038-2024"), "electricity-nl")
    ember = effective_scope(profile("ember-2025"), "electricity-nl")
    uba = effective_scope(profile("uba-strommix-2026"), "electricity-de-2024")
    assert {d["dimension"]: d["severity"] for d in differences(eea, ember)}["basis"] == "hard"
    by = {d["dimension"]: d for d in differences(eea, uba)}
    assert by["gases"]["severity"] == "hard"
    assert by["delivery"]["severity"] == "soft"  # UBA loads line losses onto the delivered kWh
    assert "gwp" not in by  # CO2 only: no GWP basis applies


def _own_factors(root: Path, a: dict, b: dict, year_b: int = 2025) -> None:
    """Two project factors, a (baseline power) and b, with the given scopes, and one
    non-regional scenario `swap` replacing a by b."""
    base = {
        "unit": "kWh",
        "values": {"climate-change": 0.3},
        "status": "ASSUMED",
        "source": "synthetic test value",
        "source_id": "synthetic-test",
    }

    def factors(d):
        d["factors"] += [
            {"id": "elec-a", "year": 2025, "scope": a, **base},
            {"id": "elec-b", "year": year_b, "scope": b, **base},
        ]

    def scope(d):
        for flow in d["flows"]:
            if flow["key"] == "feed:POWER":
                flow["factor"] = "elec-a"
                flow.pop("proxy", None)
        d["scenarios"] = [{"id": "swap", "factors": {"elec-a": "elec-b"}}]

    _edit(root, "lca/factors.yaml", factors)
    _edit(root, "lca/lca.yaml", scope)


def test_identical_declared_scopes_are_like_for_like(asu: Path) -> None:
    _own_factors(asu, FULL, FULL)
    v = _verdict(asu, "swap")
    assert v["verdict"] == "like-for-like" and v["reasons"] == []


@pytest.mark.parametrize(
    ("dimension", "other", "verdict"),
    [
        ("basis", "life-cycle", "not comparable"),
        ("gases", "co2", "not comparable"),
        ("accounting", "consumption", "not comparable"),
        ("delivery", "consumer", "proxy"),
        ("gwp", "AR6", "proxy"),
        ("mix", "residual-mix", "proxy"),
    ],
)
def test_each_dimension_decides_the_scenario_verdict(
    asu: Path, dimension: str, other: str, verdict: str
) -> None:
    _own_factors(asu, FULL, {**FULL, dimension: other})
    assert _verdict(asu, "swap")["verdict"] == verdict


def test_a_different_data_year_is_a_proxy(asu: Path) -> None:
    _own_factors(asu, FULL, FULL, year_b=2024)
    v = _verdict(asu, "swap")
    assert v["verdict"] == "proxy" and any("year differs" in r for r in v["reasons"])


def test_an_undeclared_dimension_blocks_like_for_like(asu: Path) -> None:
    _own_factors(asu, FULL, {**FULL, "gwp": None})
    v = _verdict(asu, "swap")
    assert v["verdict"] == "proxy" and any("not declared" in r for r in v["reasons"])


def test_a_declared_proxy_discloses_but_never_makes_a_hard_difference_comparable(
    asu: Path,
) -> None:
    _own_factors(asu, FULL, {**FULL, "basis": "life-cycle"})
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d["scenarios"][0].update(proxy={"feed:POWER": "different basis, disclosed"}),
    )
    assert _verdict(asu, "swap")["verdict"] == "not comparable"


def test_a_scenario_without_replaced_factors_keeps_the_background(asu: Path) -> None:
    v = _verdict(asu, "hot-climate")
    assert v["verdict"] == "like-for-like" and v["compared"] == []
    from chemeascode.domains.assessment.lca.report import results_markdown

    line = next(
        x for x in results_markdown(lca_report(asu)).splitlines() if x.startswith("- hot-climate:")
    )
    assert "no background replaced" in line and "design case hot" in line
    assert "all compared dimensions" not in line


def test_two_factors_of_one_source_share_its_undeclared_dimensions(asu: Path) -> None:
    # EEA leaves gwp undeclared: NL against DE of the same profile is still like-for-like
    _edit(
        asu, "lca/factors.yaml", lambda d: d.update(include=["desnz-ghg-2026", "eea-ener038-2024"])
    )

    def scope(d):
        for flow in d["flows"]:
            if flow["key"] == "feed:POWER":
                flow["factor"] = "eea-ener038-2024:electricity-nl"
        d["scenarios"] = [
            {
                "id": "swap",
                "factors": {"eea-ener038-2024:electricity-nl": "eea-ener038-2024:electricity-de"},
            }
        ]

    _edit(asu, "lca/lca.yaml", scope)
    v = _verdict(asu, "swap")
    diffs = {d["dimension"] for c in v["compared"] for d in c["differences"]}
    assert "gwp" not in diffs
    # from different sources, an undeclared dimension still blocks like-for-like
    eea = effective_scope(profile("eea-ener038-2024"), "electricity-nl")
    assert "gwp" in {d["dimension"] for d in differences(eea, eea)}
    assert "gwp" not in {d["dimension"] for d in differences(eea, eea, same_source=True)}


def test_undeclared_project_factors_make_a_proxy(asu: Path) -> None:
    v = _verdict(asu)  # synthetic NL factor has no scope; the UK baseline factor has one
    assert v["verdict"] == "proxy"
    assert any("not declared" in r for r in v["reasons"])


def test_a_gap_makes_the_scenario_not_comparable(asu: Path) -> None:
    v = _verdict(asu, "de-grid-2025")  # cooling water declared missing in the fixture
    assert v["verdict"] == "not comparable"
    assert any("no background for" in r for r in v["reasons"])


def _mix_findings(root: Path):
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    return [f for f in report.findings if f.rule == "cheme.lca-method-mix"]


def test_method_mix_reads_the_structured_basis(asu: Path) -> None:
    # power (UK: direct+upstream, co2e) and cooling water (life-cycle, co2e) in one category
    scope = {"basis": "life-cycle", "gases": "co2e", "gwp": "AR4/AR5"}
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(scope=scope) for f in d["factors"] if f["id"] == "cooling-water"],
    )
    (found,) = _mix_findings(asu)
    assert "basis: direct+upstream; life-cycle" in found.message


def test_method_mix_reads_the_structured_gases(asu: Path) -> None:
    scope = {"basis": "direct+upstream", "gases": "co2"}
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(scope=scope) for f in d["factors"] if f["id"] == "cooling-water"],
    )
    (found,) = _mix_findings(asu)
    assert "gases: co2; co2e" in found.message
    assert "AR4/AR5; CO2 only" in found.message  # CO2 only has no GWP basis, but differs


def test_method_mix_flags_co2_only_beside_an_unscoped_co2e_factor(asu: Path) -> None:
    # the warning projects had before the comparison basis: a project factor without scope (its
    # source's method text says AR5) beside a CO2-only packaged factor
    _edit(
        asu, "lca/factors.yaml", lambda d: d.update(include=["desnz-ghg-2026", "uba-strommix-2026"])
    )
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: d["sources"][0].update(method="GWP100, IPCC AR5"),
    )

    def power(d):
        for flow in d["flows"]:
            if flow["key"] == "feed:POWER":
                flow["factor"] = "uba-strommix-2026:electricity-de-2025"

    _edit(asu, "lca/lca.yaml", power)
    (found,) = _mix_findings(asu)
    assert "AR5; CO2 only" in found.message


def test_method_mix_reads_the_structured_gwp(asu: Path) -> None:
    scope = {"basis": "direct+upstream", "gases": "co2e", "gwp": "AR6"}
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(scope=scope) for f in d["factors"] if f["id"] == "cooling-water"],
    )
    (found,) = _mix_findings(asu)
    assert "AR4/AR5; AR6" in found.message


def test_method_mix_stays_quiet_for_equal_scopes(asu: Path) -> None:
    scope = {"basis": "direct+upstream", "gases": "co2e", "gwp": "AR4/AR5"}
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(scope=scope) for f in d["factors"] if f["id"] == "cooling-water"],
    )
    assert _mix_findings(asu) == []


def test_results_and_api_carry_the_verdict(asu: Path) -> None:
    report = lca_report(asu)
    payload = json.loads(report.to_json())
    assert payload["comparability"]["baseline"]["verdict"] == "baseline"
    assert payload["comparability"]["nl-grid-2025"]["verdict"] in (
        "like-for-like",
        "proxy",
        "not comparable",
    )
    from chemeascode.domains.assessment.lca.report import results_markdown

    text = results_markdown(report)
    assert "comparability with the baseline" in text
    assert "nl-grid-2025:" in text
    # packaged source scope reaches the API payload
    assert any(s.get("scope") for s in payload["sources"])


def test_a_source_copy_next_to_its_include_still_resolves() -> None:
    packaged = profile("desnz-ghg-2026").sources[0].model_dump(exclude={"scope"})
    data = FactorFile.model_validate(
        {
            "schema": "cheme/lca/v1",
            "kind": "lca_factors",
            "include": ["desnz-ghg-2026"],
            "sources": [packaged],
        }
    )
    resolved, problems = backgrounds.resolve(data)
    assert problems == []
    # the copy keeps the packaged scope: a hard difference stays visible
    scope, _ = effective_scope(resolved, "desnz-ghg-2026:electricity-gb")
    assert (scope.gases, scope.gwp, scope.basis) == ("co2e", "AR4/AR5", "direct+upstream")
    assert profile("desnz-ghg-2026").sources[0].scope is not None  # cached profile untouched


def test_a_source_copy_keeps_a_hard_difference_not_comparable(asu: Path) -> None:
    _with_profiles(
        asu, ["desnz-ghg-2026", "uba-strommix-2026"], "uba-strommix-2026:electricity-de-2025"
    )
    copy = profile("uba-strommix-2026").sources[0].model_dump(exclude={"scope"}, exclude_none=True)
    _edit(asu, "lca/factors.yaml", lambda d: d["sources"].append(copy))
    assert _verdict(asu)["verdict"] == "not comparable"


def test_a_sidecar_entry_matching_nothing_is_an_error(tmp_path: Path) -> None:
    sidecar = tmp_path / "p.yaml"
    sidecar.write_text("sources:\n  typo: {basis: direct}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="match nothing"):
        backgrounds._scoped(profile("egrid-2023").model_copy(deep=True), sidecar)


def test_contractual_electricity_is_a_proxy(asu: Path) -> None:
    _own_factors(asu, FULL, FULL)
    _edit(
        asu,
        "lca/lca.yaml",
        lambda d: d["scenarios"][0].update(electricity="contractual", source="PPA"),
    )
    assert _verdict(asu, "swap")["verdict"] == "proxy"


# -- data year and publication year ----------------------------------------------------------------


def test_data_year_is_compared_where_declared_and_year_keeps_its_meaning(asu: Path) -> None:
    # both factors carry year 2025; b declares that its data describe 2023
    _own_factors(asu, FULL, FULL)
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(data_year=2023) for f in d["factors"] if f["id"] == "elec-b"],
    )
    v = _verdict(asu, "swap")
    assert v["verdict"] == "proxy"
    (year,) = [d for c in v["compared"] for d in c["differences"] if d["dimension"] == "year"]
    assert (year["baseline"], year["scenario"]) == (2025, 2023)
    # which year each side was compared on is stated
    assert v["compared"][0]["years"] == {"baseline": "year", "scenario": "data_year"}
    assert any("[year / data_year]" in r for r in v["reasons"])
    data = FactorFile.model_validate(yaml.safe_load((asu / "lca/factors.yaml").read_text()))
    assert next(f for f in data.factors if f.id == "elec-b").year == 2025


def test_a_publication_year_alone_changes_no_comparison(asu: Path) -> None:
    _own_factors(asu, FULL, FULL)
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(publication_year=2026) for f in d["factors"] if f["id"] == "elec-b"],
    )
    assert _verdict(asu, "swap")["verdict"] == "like-for-like"


def test_a_data_year_after_the_publication_year_is_refused() -> None:
    with pytest.raises(ValueError, match="after publication_year"):
        FactorFile.model_validate(
            {
                "schema": "cheme/lca/v1",
                "kind": "lca_factors",
                "categories": [{"id": "cc", "unit": "kg CO2-eq"}],
                "factors": [
                    {
                        "id": "x",
                        "unit": "kWh",
                        "values": {"cc": 0.1},
                        "status": "ASSUMED",
                        "source": "synthetic test value",
                        "year": 2026,
                        "data_year": 2027,
                        "publication_year": 2026,
                    }
                ],
            }
        )


def test_desnz_year_is_its_publication_year_and_only_electricity_has_a_data_year() -> None:
    for factor in profile("desnz-ghg-2026").factors:
        data_year = 2025 if factor.id.startswith("electricity-") else None
        assert (factor.year, factor.publication_year, factor.data_year) == (2026, 2026, data_year)
    # the other packaged profiles declare no years: their records keep their bytes
    for name in ("egrid-2023", "eea-ener038-2024", "ember-2025", "uba-strommix-2026"):
        assert all(
            f.data_year is None and f.publication_year is None for f in profile(name).factors
        )


def test_records_carry_declared_years_only(asu: Path) -> None:
    _own_factors(asu, FULL, FULL)
    _edit(
        asu,
        "lca/factors.yaml",
        lambda d: [f.update(data_year=2024) for f in d["factors"] if f["id"] == "elec-b"],
    )
    report = lca_report(asu)
    swap = next(
        x
        for x in record(report, "swap")["linked_inventory"]["exchanges"]
        if x["key"] == "feed:POWER"
    )
    base = next(
        x
        for x in record(report, "baseline")["linked_inventory"]["exchanges"]
        if x["key"] == "feed:POWER"
    )
    assert swap["data_year"] == 2024 and "publication_year" not in swap
    assert "data_year" not in base and "publication_year" not in base


def test_desnz_records_carry_the_electricity_data_year_only() -> None:
    # publication_year is never written into a record; the declared data year of the DESNZ
    # electricity factor (2025) is, on the electricity exchanges and nowhere else
    root = FIXTURE
    base = record(lca_report(root), "baseline")
    assert "publication_year" not in json.dumps(base, sort_keys=True)
    exchanges = base["linked_inventory"]["exchanges"]
    with_year = {x["key"] for x in exchanges if "data_year" in x}
    assert with_year == {"feed:POWER"}
    assert all(x["data_year"] == 2025 for x in exchanges if "data_year" in x)
    v = record(lca_report(root), "nl-grid-2025")["comparability"]
    # the pair that meets the DESNZ electricity factor says which year field was read
    assert all(c["years"] == {"baseline": "data_year", "scenario": "year"} for c in v["compared"])


def test_a_sidecar_year_entry_is_checked(tmp_path: Path) -> None:
    sidecar = tmp_path / "p.yaml"
    sidecar.write_text('years:\n  "*": {year: 2020}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="only data_year and publication_year"):
        backgrounds._scoped(profile("egrid-2023").model_copy(deep=True), sidecar)
    sidecar.write_text('years:\n  "*": {data_year: "2020"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="is no year"):
        backgrounds._scoped(profile("egrid-2023").model_copy(deep=True), sidecar)
    for bad in ('years:\n  "*": 2026\n', "years: [a]\n", 'years:\n  "*":\n'):
        sidecar.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="a mapping of factor id glob"):
            backgrounds._scoped(profile("egrid-2023").model_copy(deep=True), sidecar)


@pytest.mark.parametrize("first", ["all", "electricity"])
def test_every_matching_sidecar_year_entry_counts(tmp_path: Path, first: str) -> None:
    entries = {
        "all": '  "*": {publication_year: 2026}\n',
        "electricity": '  "electricity-*": {data_year: 2025}\n',
    }
    other = "electricity" if first == "all" else "all"
    sidecar = tmp_path / "p.yaml"
    sidecar.write_text("years:\n" + entries[first] + entries[other], encoding="utf-8")
    data = backgrounds._scoped(profile("desnz-ghg-2026").model_copy(deep=True), sidecar)
    gb = next(f for f in data.factors if f.id == "electricity-gb")
    gas = next(f for f in data.factors if f.id == "natural-gas-gb")
    assert (gb.data_year, gb.publication_year) == (2025, 2026)
    assert (gas.data_year, gas.publication_year) == (None, 2026)


def test_sidecar_year_conflicts_are_errors(tmp_path: Path) -> None:
    sidecar = tmp_path / "p.yaml"
    sidecar.write_text(
        'years:\n  "*": {data_year: 2024}\n  "electricity-*": {data_year: 2025}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="two values of data_year"):
        backgrounds._scoped(profile("desnz-ghg-2026").model_copy(deep=True), sidecar)
    sidecar.write_text('years:\n  "*": {data_year: 2027, publication_year: 2026}\n')
    with pytest.raises(ValueError, match="data_year after publication_year"):
        backgrounds._scoped(profile("desnz-ghg-2026").model_copy(deep=True), sidecar)


def test_a_year_in_the_profile_file_wins_over_the_sidecar(tmp_path: Path) -> None:
    found = profile("desnz-ghg-2026").model_copy(deep=True)
    found.factors[0].data_year = 2024
    sidecar = tmp_path / "p.yaml"
    sidecar.write_text('years:\n  "*": {data_year: 2025}\n', encoding="utf-8")
    data = backgrounds._scoped(found, sidecar)
    assert data.factors[0].data_year == 2024 and data.factors[1].data_year == 2025
