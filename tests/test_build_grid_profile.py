"""scripts/build_grid_profile.py (pre-release issue 306 step 4): one declared basis from the user's
own copy of Ember's long-format CSV. The CSV here is synthetic; its numbers are test values."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca.schemas import FactorFile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("grid", ROOT / "scripts/build_grid_profile.py")
grid = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grid)

HEAD = "Area,ISO 3 code,Year,Area type,Category,Variable,Unit,Value\n"


def _csv(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "ember.csv"
    path.write_text(HEAD + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def _row(area, iso3, year, value, unit="gCO2/kWh", var="CO2 intensity", kind="Country or economy"):
    return f"{area},{iso3},{year},{kind},Power sector emissions,{var},{unit},{value}"


def _build(path, countries=None, **kw):
    args = dict(year=2025, release="test release", downloaded="2026-10-26", publication_year=None)
    args.update(kw)
    return grid.build(path, args.pop("year"), countries, args.pop("release"),
                      args.pop("downloaded"), args.pop("publication_year"))  # fmt: skip


def test_one_declared_basis_and_valid_factor_file(tmp_path):
    path = _csv(
        tmp_path,
        _row("Germany", "DEU", 2025, 329.65),
        _row("Netherlands", "NLD", 2025, 250.5),
        _row("Germany", "DEU", 2024, 337.12),
    )
    data, notes = _build(path, publication_year=2026)
    parsed = FactorFile.model_validate(yaml.safe_load(yaml.safe_dump(data)))
    assert [f.id for f in parsed.factors] == ["electricity-de", "electricity-nl"]
    de = parsed.factors[0]
    assert de.values["climate-change"] == pytest.approx(0.32965)
    assert (de.year, de.data_year, de.publication_year) == (2025, 2025, 2026)
    (source,) = parsed.sources
    scope = source.scope
    assert (scope.basis, scope.gases, scope.accounting, scope.delivery, scope.mix) == (
        "direct",
        "co2",
        "generation",
        "generation",
        "grid-average",
    )
    assert scope.gwp is None  # CO2 only: no GWP basis
    assert source.licence == "CC-BY-4.0" and source.attribution.startswith("Ember")
    assert source.checksum == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert notes == []


def test_missing_economy_and_unreadable_value_are_listed_not_guessed(tmp_path):
    path = _csv(tmp_path, _row("Germany", "DEU", 2025, 300), _row("France", "FRA", 2025, ""))
    data, notes = _build(path, ["DE", "FR", "NL"])
    assert [f["location"] for f in data["factors"]] == ["DE"]
    text = " | ".join(notes)
    assert "France" in text and "not a number" in text and "NL: no CO2 intensity" in text


def test_regions_other_variables_and_other_years_are_not_read(tmp_path):
    path = _csv(
        tmp_path,
        _row("Germany", "DEU", 2025, 300),
        _row("European Union", "EU", 2025, 200, kind="Region"),
        _row("Germany", "DEU", 2025, 9, var="Total emissions", unit="mtCO2"),
    )
    data, _ = _build(path)
    assert [f["location"] for f in data["factors"]] == ["DE"]


def test_a_changed_unit_stops_the_read(tmp_path):
    path = _csv(tmp_path, _row("Germany", "DEU", 2025, 0.3, unit="kgCO2/kWh"))
    with pytest.raises(ValueError, match="unit"):
        _build(path)


def test_a_file_in_another_format_is_refused(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not Ember's long format"):
        _build(path)


def test_unknown_country_and_empty_result_are_errors(tmp_path):
    path = _csv(tmp_path, _row("Germany", "DEU", 2025, 300))
    with pytest.raises(ValueError, match="XX"):
        _build(path, ["XX"])
    with pytest.raises(ValueError, match="no factor"):
        _build(path, ["NL"])


def test_main_writes_a_file_and_reports(tmp_path, capsys):
    path = _csv(tmp_path, _row("Germany", "DEU", 2025, 300))
    out = tmp_path / "grid.yaml"
    code = grid.main(
        [
            str(path),
            "--year",
            "2025",
            "--release",
            "r",
            "--downloaded",
            "2026-10-26",
            "--output",
            str(out),
        ]  # fmt: skip
    )
    assert code == 0 and "1 factor" in capsys.readouterr().out
    assert yaml.safe_load(out.read_text())["factors"][0]["location"] == "DE"
    assert grid.main([str(tmp_path / "none.csv"), "--year", "1", "--release", "r",
                      "--downloaded", "d"]) == 2  # fmt: skip


def test_the_written_scope_makes_countries_like_for_like_and_ember_life_cycle_not(tmp_path):
    """The scope the script writes is what the verdict reads."""
    from chemeascode.domains.assessment.lca import backgrounds
    from chemeascode.domains.assessment.lca.comparability import differences, effective_scope

    path = _csv(tmp_path, _row("Germany", "DEU", 2025, 300), _row("France", "FRA", 2025, 50))
    parsed = FactorFile.model_validate(yaml.safe_load(yaml.safe_dump(_build(path)[0])))
    de = effective_scope(parsed, "electricity-de")
    fr = effective_scope(parsed, "electricity-fr")
    assert differences(de, fr, same_source=True) == []
    life_cycle = backgrounds.profile("ember-2025")
    other = effective_scope(life_cycle, "electricity-de")
    found = {d["dimension"]: d["severity"] for d in differences(de, other)}
    assert found["basis"] == "hard" and found["gases"] == "hard"
