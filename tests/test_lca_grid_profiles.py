"""Open grid electricity profiles: every value sourced, the terms recorded.

The expected values are read from the publishers' files independently of the generator:
eGRID2023 rev2 US23!X3 (770.884), SRL23 Z6 CAMX (429.983) and Z7 ERCT (736.629), in lb CO2e/MWh
x 0.45359237/1000; EEA ENER038 2024 and Ember yearly data 2025, in g CO2e/kWh.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca.backgrounds import profile, profiles, resolve
from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.domains.assessment.lca.scenarios import record
from chemeascode.domains.assessment.lca.schemas import FactorFile

GRID = ("egrid-2023", "eea-ener038-2024", "ember-2025", "uba-strommix-2026")
# fmt: off
EU27 = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT",
    "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}
# fmt: on
FIXTURE = Path(__file__).parent / "data" / "lca-scenarios-asu"


def _value(name: str, factor: str) -> float:
    return next(f for f in profile(name).factors if f.id == factor).values["climate-change"]


@pytest.mark.parametrize("name", GRID)
def test_each_profile_states_its_source_and_terms(name: str) -> None:
    assert name in profiles()
    data = profile(name)
    (source,) = data.sources
    assert source.id == name
    assert source.publication == "public" and source.redistribution
    assert source.licence and source.attribution and source.url.startswith("https://")
    assert source.checksum.startswith("sha256:") and source.version and source.method
    for factor in data.factors:
        assert factor.source_id == name
        assert factor.status in ("PUBLISHED", "ESTIMATE") and factor.unit == "kWh"
        assert factor.location and factor.year
        # every value says where in the file it was read
        assert any(word in factor.source for word in ("sheet", "line", "file", "page")), factor.id
        assert 0 <= factor.values["climate-change"] < 1.5, factor.id


@pytest.mark.parametrize(
    ("name", "factor", "expected"),
    [
        ("egrid-2023", "electricity-us", 770.884 * 0.45359237 / 1000),
        ("egrid-2023", "electricity-us-erct", 736.629 * 0.45359237 / 1000),
        ("egrid-2023", "electricity-us-camx", 429.983 * 0.45359237 / 1000),
        ("eea-ener038-2024", "electricity-eu27", 0.18344),
        ("eea-ener038-2024", "electricity-de", 0.291),
        ("eea-ener038-2024", "electricity-nl", 0.245),
        ("eea-ener038-2024", "electricity-fr", 0.036),
        ("ember-2025", "electricity-us", 0.384403),
        ("ember-2025", "electricity-de", 0.334117),
        ("ember-2025", "electricity-nl", 0.253664),
        ("ember-2025", "electricity-gb", 0.218001),
        ("ember-2025", "electricity-eu27", 0.210536),
        ("desnz-ghg-2026", "electricity-gb", 0.18436),
        # UBA summary page of 2026-03-23: 379 / 353 / 344 g CO2 per kWh consumed in Germany
        ("uba-strommix-2026", "electricity-de-2023", 0.379),
        ("uba-strommix-2026", "electricity-de-2024", 0.353),
        ("uba-strommix-2026", "electricity-de-2025", 0.344),
    ],
)
def test_spot_values_match_the_publishers_files(name: str, factor: str, expected: float) -> None:
    assert _value(name, factor) == pytest.approx(expected, abs=1e-6)


def test_coverage_of_each_profile() -> None:
    egrid = {f.location for f in profile("egrid-2023").factors}
    assert "US" in egrid and len([g for g in egrid if g.startswith("US-")]) == 27
    eea = {f.location for f in profile("eea-ener038-2024").factors}
    assert eea == EU27 | {"EU27"}
    ember = {f.location for f in profile("ember-2025").factors}
    assert {"US", "GB", "DE", "NL", "FR", "CN", "IN", "JP", "EU27", "GLO"} <= ember
    assert ember >= EU27


def test_uba_is_direct_co2_territorial_with_its_own_terms_and_provisional_years() -> None:
    from chemeascode.domains.assessment.lca.report import _method

    data = profile("uba-strommix-2026")
    (source,) = data.sources
    # not a CC licence, and the PDF is not packaged
    assert "Not a Creative Commons licence" in source.licence and "12a EGovG" in source.licence
    assert "UBA named in the source note" in source.licence
    assert "Umweltbundesamt" in source.attribution and "(changed)" in source.attribution
    assert source.method.startswith("direct CO2 only")
    assert _method(source.method) != _method(profile("egrid-2023").sources[0].method)
    assert _method(source.method) not in ("AR4", "AR5", "AR6", "AR4/AR5")  # flagged as a mix
    # the scope the page's loose wording hides: territorial, generation-based, no trade balance
    assert "territorial, generation-based factor, not a trade-adjusted consumption" in source.notes
    assert "net of plant own use, pumped-storage input and line" in source.notes
    by_year = {f.year: f for f in data.factors}
    assert list(by_year) == [2023, 2024, 2025]  # only the page's three figures
    for factor in by_year.values():
        assert "territorial basis, no trade balance" in factor.title
    assert "provisional" in by_year[2024].title and by_year[2024].status == "PUBLISHED"
    # UBA's own estimate must keep results screening: ESTIMATE, with basis and validity stated
    assert "estimated" in by_year[2025].title and by_year[2025].status == "ESTIMATE"
    assert "not derived by this project" in by_year[2025].basis and by_year[2025].validity
    assert by_year[2023].status == "PUBLISHED"


def test_scope_is_named_in_every_title() -> None:
    for factor in profile("egrid-2023").factors + profile("eea-ener038-2024").factors:
        assert "direct" in factor.title, factor.id
    for factor in profile("ember-2025").factors:
        assert "life cycle" in factor.title, factor.id


def test_life_cycle_and_direct_profiles_are_told_apart_by_the_method_check() -> None:
    from chemeascode.domains.assessment.lca.report import _method

    basis = {name: _method(profile(name).sources[0].method) for name in GRID}
    assert basis["egrid-2023"] == basis["eea-ener038-2024"] == "AR5"
    # the direct-CO2-only UBA series is told apart from the AR5 CO2e profiles and from Ember
    assert basis["uba-strommix-2026"] not in ("AR4", "AR5", "AR6", basis["ember-2025"])
    # mixing life-cycle Ember with the direct AR5 profiles is flagged (cheme.lca-method-mix)
    assert basis["ember-2025"] not in ("AR4", "AR5", "AR6")


def test_attribution_links_the_licence_where_it_asks_for_it() -> None:
    assert "creativecommons.org/licenses/by/4.0" in profile("ember-2025").sources[0].attribution
    assert "eea.europa.eu" in profile("eea-ener038-2024").sources[0].attribution


def test_all_profiles_resolve_together() -> None:
    merged, problems = resolve(
        FactorFile.model_validate(
            {"schema": "cheme/lca/v1", "kind": "lca_factors", "include": list(GRID)}
        )
    )
    assert problems == []
    ids = {f.id for f in merged.factors}
    assert {"egrid-2023:electricity-us-erct", "eea-ener038-2024:electricity-de"} <= ids
    assert "uba-strommix-2026:electricity-de-2024" in ids


def test_a_regional_scenario_links_a_sourced_grid_factor(tmp_path: Path) -> None:
    root = tmp_path / "asu"
    shutil.copytree(FIXTURE, root)
    factors = yaml.safe_load((root / "lca/factors.yaml").read_text())
    factors["include"] = ["desnz-ghg-2026", "eea-ener038-2024"]
    (root / "lca/factors.yaml").write_text(yaml.safe_dump(factors, sort_keys=False))
    scope = yaml.safe_load((root / "lca/lca.yaml").read_text())
    scope["scenarios"][1]["factors"] = {
        "desnz-ghg-2026:electricity-gb": "eea-ener038-2024:electricity-de"
    }
    scope["scenarios"][1]["year"] = 2024
    (root / "lca/lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    de = record(report, "de-grid-2025")
    power = next(e for e in de["linked_inventory"]["exchanges"] if e["key"] == "feed:POWER")
    assert (power["background"], power["location"], power["year"]) == (
        "eea-ener038-2024:electricity-de",
        "DE",
        2024,
    )
    assert power["source_id"] == "eea-ener038-2024"
    # the DE grid no longer warns as another geography; the cooling water stays declared missing
    assert not any(
        "electricity" in w["message"]
        for w in de["warnings"]
        if w["rule"] == "cheme.lca-scenario-geography"
    )
    assert de["publication"]["publishable"] is True
